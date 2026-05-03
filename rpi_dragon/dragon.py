#!/usr/bin/env python3

import os
import sys
import socket
import pyaudio
import re
from threading import Thread, Lock
from time import sleep
import logging
import traceback

# temporary fix to exclude characters that might mess up the console output.
# https://www.asciitable.com/
# https://serverfault.com/questions/189520/which-characters-if-catd-will-mess-up-my-terminal-and-make-a-ton-of-noise

#===========================================================================

class Dragon(Thread):
  def __init__(
      self,
      interfaces = [],
      chunk_size = 1024,
      print_enabled = False,
      color_enabled = False,
      linebreak_enabled = True,
      audio_device_index = 0,
      sample_rate = 48000,
      sample_width = 1, # width * 8 = bit depth
      log_aps = True,
      audio_only = False,
      qty_channels = 2
    ):
    if os.getuid() != 0:
      raise Exception('This module requires root priviledges.')
    super().__init__()
    self.daemon = True
    self.interfaces = interfaces
    self.qty_channels = qty_channels
    self.lock = Lock()
    self.sockets = None
    self.writer = None
    self.audifier = None
    self.audio_device_index = audio_device_index
    self.chunk_size = chunk_size
    self.sample_rate = sample_rate
    self.sample_width = sample_width
    self.print_enabled = print_enabled
    self.colorEnabled = color_enabled
    self.linebreak_enabled = linebreak_enabled
    self.log_aps = log_aps
    self.doRun = False
    self.isStopped = True
    self.isReady = False
    self.audio_only = audio_only

    logging.debug(f"DEVICE: {self.audio_device_index}")
    logging.debug(f"interfaces: {self.interfaces}")
    logging.debug(f"qty_channels: {self.qty_channels}")
    logging.debug(f"chunk_size : {self.chunk_size}")
    logging.debug(f"SAMPLE RATE: {self.sample_rate}")
    logging.debug(f"BYTES PER SAMPLE: {self.sample_width}")
    logging.debug(f"PRINT: {self.print_enabled}")
    logging.debug(f"COLOR: {self.colorEnabled}")
    logging.debug(f"CONTROL_CHARACTERS: {self.linebreak_enabled}")
    logging.debug(f"LOG APs: {self.log_aps}")
    logging.debug(f"audio_only: {self.audio_only}")

  #----------------------------------------------------------------

  def audify_data_callback(self, in_data, frame_count, time_info, status):
    if len(self.sockets.listeners) == 0:
      audioChunk = bytearray([127] * frame_count * self.qty_channels)
      printQueue = []
    else: 
      audioChunk, printQueue = self.sockets.extractFrames(frame_count, self.qty_channels)
    if self.writer:
      self.writer.queueForPrinting(printQueue)
    return(bytes(audioChunk), pyaudio.paContinue)

  #----------------------------------------------------------------

  def run(self):
    self.doRun = True

    # Spin up the network socket listeners
    try:
      self.sockets = SocketReader(
        self.interfaces,
        max_listeners = self.qty_channels
      )
      self.sockets.start()
    except Exception as e:
      logging.error('Error starting socket listeners: %s' % repr(e))

    # Spin up the console outoput
    try:
      if not self.audio_only:
        self.writer = Writer(
          qty_channels = self.qty_channels,
          chunk = self.chunk_size * self.qty_channels,
          color = self.colorEnabled,
          linebreaks = self.linebreak_enabled,
          enabled = self.print_enabled
        )
        self.writer.start()
    except Exception as e:
      logging.error('Error starting console writers: %s' % repr(e))

    # Spin up the audio playback engine
    try:
      self.audifier = Audifier(
        qty_channels = self.qty_channels,
        width = self.sample_width,
        rate = self.sample_rate,
        chunk = self.chunk_size,
        audio_device_index = self.audio_device_index,
        callback = self.audify_data_callback
      )
      self.audifier.start()
    except Exception as e:
      logging.error('Error starting audifiers: %s' % repr(e))

    self.isStopped = False
    self.isReady = True
  
    while self.doRun:
      sleep(5.0)
      logging.debug(self.get_state())

    self.isStopped = True

  #----------------------------------------------------------------

  def stop(self):
    self.doRun = False

    while not self.isStopped:
      sleep(0.01)

    if not self.audio_only:
      try:
        logging.info('Stopping Writer...')
        if self.writer.color:
          self.writer.stop()
          sys.stdout.write('\x1b[0m')
        self.writer.stop()
      except Exception as e:
        logging.error("Error stopping Writer: %s" % repr(e))

    # Shutdown the PyAudio instance
    logging.info('Stopping audio stream...')
    try:
      self.audifier.stop()
    except Exception as e:
      logging.error("Failed to terminate PyAudio instance: %s" % repr(e))

    # close the sockets
    logging.info('Closing Listener...')
    try:
      self.sockets.stop()
    except Exception as e:
      logging.error("Error closing socket: %s" % repr(e))

    logging.info('The Dragon Sleeps!')
    self.join()

  #----------------------------------------------------------------

  def get_state(self):

    return {
      'chunk_size' : self.chunk_size,
      'audio_device_index' : self.audio_device_index,
      'audio_channels': self.qty_channels,
      'sample_rate' : self.sample_rate,
      'sample_width' : self.sample_width, # width * 8 = bit depth
      'audio_only' : self.audio_only,
      'writer' : self.get_writer_state(),
      'sockets' : self.get_sockets_state()
    }

  def get_writer_state(self):
    return self.writer.getState() if self.writer else None

  def get_sockets_state(self):
    return self.sockets.get_state() if self.sockets else None

  def get_socket_state(self, index):
    return self.sockets.get_socket_state(index) if self.sockets else None

  def get_access_points(self):
    return self.sockets.get_access_points()

  def set_socket_interface(self, index, interface):
    return self.sockets.set_listener(index, interface)

#===========================================================================
# Listener
# Helps manage sockets

class Listener():
  def __init__(self, interface=None, buffer_size_limit=16777216):
    self.interface = interface
    self.socket = None
    self.buffer = bytearray() # data will be into and out of the buffer(s)
    self.buffer_size_limit = buffer_size_limit

    self.initSocket(self.interface)

  def initSocket(self, interface):
    if interface:
      try:
        if s := self.createSocket(interface):
          self.socket = s
        else:
          self.socket = None
      except OSError as e:
        logging.warning(f"Listener.initSocket(): {interface} {repr(e)}")
      except Exception as e:
        logging.error(f"Listener.initSocket(): {repr(e)}")

  def createSocket(self, interface):
    # etablishes a RAW socket on the given interface, e.g. eth0. meant to only be read.
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0003))
    s.bind((interface, 0))
    s.setblocking(False) # non-blocking
    return s

  def clearBuffer(self):
    self.buffer = bytearray()

  def read(self, qty_bytes=65535):
    if not self.socket: return

    try: # grab a chunk of data from the socket...
      if data := self.socket.recv(qty_bytes):
        # logging.debug(f"Socket iface: {self.interface}, bytes captured {len(data)}")
        if len(self.buffer) < self.buffer_size_limit:
          self.buffer.extend(data)
          return data
    except OSError: # if there's no data to be read. the socket will throw and exception
      pass
    except Exception as e:
        logging.warning(f"Listener.read(): {e}")

  def extract_bytes(self, qty_bytes):
    # logging.debug(f"Socket iface: {self.interface}, buffer size before: {len(self.buffer)}")
    data = self.buffer[:qty_bytes]
    self.buffer = self.buffer[qty_bytes:]
    # logging.debug(f"Socket iface: {self.interface}, bytes extracted {len(data)} buffer size after: {len(self.buffer)}")
    return data

  def close(self):
    if socket:
      self.socket.close()
      self.socket = None

  def is_open(self):
    return self.socket != None

  def get_state(self):
    return {
      'interface' : self.interface,
      'is_open' : self.is_open(),
      'buffer_size' : len(self.buffer)
    }

# A socket based packet sniffer. Main loop will check sockets for data and grab what's there,
# storing in a buffer to be extracted later. chunk should be a relatively small power of two.
# Until I can figure out a way to tinker with the sockets and set appropriate permissions, this
# is what requires running the script as root.

class SocketReader(Thread):
  def __init__(self, interfaces=[], chunk=4096, log_aps=True, buffer_size_limit=16777216, max_listeners=2):
    super().__init__()
    self.daemon = True
    self.lock = Lock()
    self.interfaces = interfaces
    self.chunk = chunk # used to fine tune how much is "grabbed" from the socket
    self.listeners = [None] * max_listeners
    self.doRun = False # flag to run main loop & help w/ smooth shutdown of thread
    self.APs = {}
    self.log_aps = log_aps
    self.buffer_size_limit = buffer_size_limit
    self.max_listeners = max_listeners

    self.init_listeners(interfaces)

  def init_listeners(self, interfaces):
    self.listeners = [None] * self.max_listeners
    for i in range(self.max_listeners):
      if i < len(interfaces):
        self.set_listener(i, interfaces[i])
      else:
        self.set_listener(i, None)

  def set_listener(self, index, interface):
    if index < len(self.listeners):
      if self.listeners[index]: self.listeners[index].close
      self.listeners[index] = Listener(
        interface = interface,
        buffer_size_limit = self.buffer_size_limit
      )

  def add_listener(self, interface):
    if len(self.listeners) < self.max_listeners:
      self.listeners.append(
        Listener(interface = interface)
      )

  def remove_listener(self, interface):
    self.listeners = [listener for listener in self.listeners if listener.interface != interface]

  def get_access_points(self):
    return self.APs.copy()

  def get_state(self):

    return {
      'log_aps' : self.log_aps,
      'buffer_size_limit' : self.buffer_size_limit,
      'sockets' : [listener.get_state() for listener in self.listeners]
    }

  def get_socket_state(self, index):
    return self.listeners[index].get_state() if index < len(self.listeners) else None

  def analyzePacket(self, pkt):
    AP = {}
    SSID = None
    MAC = None
    type = None
    try:
      if pkt[25] >> 4 & 0b1111 == 0x4 and pkt[25] >> 2 & 0b11 == 0:
        if pkt[49] == 0 and pkt[50] > 0:
          try:
            SSID = pkt[51:51+pkt[50]].decode('utf-8')
            MAC = pkt[29:35].hex()
            type = 0
          except:
            pass
        if not SSID and pkt[54] == 0 and pkt[55] > 0:
          try:
            SSID = pkt[56:56+pkt[55]].decode('utf-8')
            MAC = pkt[29:35].hex()
            type = 1
          except:
            pass
        if SSID:
          
          return {
            'ssid' : SSID,
            'mac' : MAC,
            'type' : type
          }  
    except:
      return None
      pass

  def addToAPs(self, AP):
    ssid = AP['ssid']
    with self.lock:
      if not AP['ssid'] in self.APs.keys():
        self.APs.update({ssid: {
          'mac_addresses' : [AP['mac']],
          'count' : 1,
          'type' : AP['type']
        }})
      else:
        if not AP['mac'] in self.APs[ssid]['mac_addresses']:
          self.APs[ssid]['mac_addresses'].append(AP['mac'])
        self.APs[ssid]['count'] += 1

  def readSockets(self):
    for listener in self.listeners:
      if data := listener.read():
        if self.log_aps:
           if AP := self.analyzePacket(data): # extract APs
              self.addToAPs(AP)

  def extractFrames(self, frames, qty_channels):
    slices = [] # for making the chunk of audio data
    printQueue = [] # for assembling the data into chunks for printing  
    for i in range(qty_channels):
      if i+1 > len(self.listeners) or not self.listeners[i].socket:
        slices.append(bytes([127]) * (frames))
        continue
      with self.lock:
        bufferSlice = self.listeners[i].extract_bytes(frames) # grab a slice of data from the buffer
      printQueue.append(bufferSlice) # whatever we got, add it to the print queue. no need to pad
      # this makes sure we return as many frames as requested, by padding with audio "0"
      padded = bufferSlice + bytes([127]) * (frames - len(bufferSlice))
      slices.append(padded)
    match qty_channels:
      case 2: # interleave the slices to form a stereo chunk
        audioChunk = [ x for y in zip(slices[0], slices[1]) for x in y ]
      case 1: # marvelous mono, just take data from the 1st slot
        audioChunk = slices[0]
      case _:
        raise Exception("[!] Only supports 1 or two channels.")
    return audioChunk, printQueue

  def run(self):
    logging.info('[SOCKET READER] run()')
    self.doRun = True
    while self.doRun:
      try:
        self.readSockets()
        sleep(0.0001)
      except Exception as e:
        logging.error('[SOCKET READER] Error executing readSockets(): %s' % repr(e))


  def stop(self):
    logging.info('[SOCKET READER] stop()')
    self.doRun=False
    try:
      for listener in self.listeners:
        if listener: listener.close()
    except Exception as e:
      logging.error('While closing socket: %e' % repr(e))
    self.join()

#===========================================================================
# Writer
# Handles console print operations in an independent thread. To prevent backlog of print data,
# The chunk should be set to the same value as for the audio device. Right now, this is done
# in the initialization portion of the script when run as standalone.

class Writer(Thread):
  def __init__(self, qty_channels, chunk=4096, color=False, linebreaks=True, enabled=False):
    super().__init__()
    self.lock = Lock()
    self.qty_channels = qty_channels # we need to know how many streams of data we'll be printing
    self.doRun = False
    self.color = color
    self.linebreaks = linebreaks
    self.shift = 0
    self.enabled = enabled
    self.buffers = []
    self.initBuffers() # the so called printQueue
    self.chunk = chunk
    self.excludedChars = [1,2,3,4,5,6,7,8,9,11,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,155,255]
    # ^ temporary fix to exclude characters that might mess up the console output.
    # https://www.asciitable.com/
    # https://serverfault.com/questions/189520/which-characters-if-catd-will-mess-up-my-terminal-and-make-a-ton-of-noise

  def initBuffers(self):
    self.buffers = []
    for i in range(self.qty_channels):
      self.buffers.append(bytearray())
    return self.buffers

  def queueForPrinting(self, queueData):
    if not self.enabled: return

    if len(queueData) != len(self.buffers):
      raise Exception("[!] len(queueData): %s != len(self.buffers): %s" % (len(queueData),len(self.buffers)))
    for i in range(len(self.buffers)):
      if queueData[i]:
        with self.lock:
          self.buffers[i].extend(queueData[i])

  def printBuffers(self):

    for n in range(len(self.buffers)):
      string = ''

      if self.chunk > len(self.buffers[n]):
        size = len(self.buffers[n])
      else:
        size = self.chunk

      if self.enabled:

        for i in range(size):
          char = chr(0)
          val = self.buffers[n][i]

          if self.linebreaks:
            TEST = True
          else:
            TEST = val > 31

          if TEST and not val in self.excludedChars:
            char = chr(val)
          if self.color: # add the ANSI escape sequence to encode the background color to value of val
            color = (val+self.shift+256)%256 # if we want to specify some amount of color shift...
            string += '\x1b[48;5;%sm%s' % (int(color), char)
          else:
            string += char
        if self.color:
          string += '\x1b[0m'

        sys.stdout.write(string)
        sys.stdout.flush()

      with self.lock:
        self.buffers[n] = self.buffers[n][size:] # remove chunk from queue. will empty over time if disabled

  def getState(self):
    return {
      'is_enabled': self.enabled,
      'color_enabled': self.color,
      'linebreaks_enabled': self.linebreaks,
      'shift': self.shift,
    }

  def printEnable(self, value):
    with self.lock:
      if value:
        self.enabled = True
      else:
        self.enabled = False

  def colorEnable(self, value):
    with self.lock:
      if value:
        self.color = True
      else:
        self.color = False

  def linebreaksEnable(self, value):
    with self.lock:
      if value:
        self.linebreaks = True
      else:
        self.linebreaks = False

  def setColorShift(self, value):
    with self.lock:
      try:
        value = int(value)
      except:
        value = 0
      self.shift = value

  def run(self):
    logging.info('[WRITER] run()')
    self.doRun = True
    while self.doRun:
      try:
        self.printBuffers()
        sleep(0.001)
      except Exception as e:
        logging.error('[WRITER] Error while executing printBuffers(): %s' % repr(e))

  def stop(self):
    logging.info('[WRITER] stop()')
    self.doRun=False
    os.system('reset')
    self.join()

#===========================================================================
# Audifer
# PyAudio stream instance and operations. By default pyAudio opens the stream in its own thread.
# Callback mode is used. Documentation for PyAudio states the process
# for playback runs in a separate thread. Initializing in a subclassed Thread may be redundant.

class Audifier():
  def __init__(self, qty_channels, width=1, rate=44100, chunk=2048, audio_device_index=0, callback=None):
    if not callback:
      raise Exception('Audifier instance requires a callback function. Got: %s' % callback)

    self.qty_channels = qty_channels
    self.width = width
    self.rate = rate
    self.chunk = chunk
    self.audio_device_index = audio_device_index
    self.callback = callback
    self.pa = pyaudio.PyAudio()
    self.stream = self.initPyAudioStream()

  def initPyAudioStream(self):

    # These are here for debugging purposes...
    # for some reason, HDMI output eludes me.
    # print('format:', self.pa.get_format_from_width(self.width))
    
    # print(
    #   self.pa.is_format_supported(
    #     rate = self.rate,
    #     output_device=self.audio_device_index,
    #     output_channels=self.qty_channels,
    #     output_format=self.pa.get_format_from_width(self.width)
    #   )
    # )

    stream = self.pa.open(
      format = self.pa.get_format_from_width(self.width),
      channels = self.qty_channels,
      rate = self.rate,
      frames_per_buffer = self.chunk,
      input = False,
      output_device_index = self.audio_device_index,
      output = True,
      stream_callback = self.callback,
      start = False
    )
    return stream

  def start(self):
    logging.info('[AUDIFIER] run()')
    logging.debug("Starting audio stream...")
    self.stream.start_stream()
    if self.stream.is_active():
      logging.debug("Audio stream is active.")

  def stop(self):
    logging.info('[AUDIFIER] stop()')
    self.stream.close()
    self.pa.terminate()
