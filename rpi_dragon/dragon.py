#!/usr/bin/env python3

import os
import sys
import socket
import pyaudio
import re
from threading import Thread, Lock
from time import sleep
import logging

# temporary fix to exclude characters that might mess up the console output.
# https://www.asciitable.com/
# https://serverfault.com/questions/189520/which-characters-if-catd-will-mess-up-my-terminal-and-make-a-ton-of-noise

#===========================================================================


class Dragon(Thread):
  def __init__(
      self,
      interfaces = '',
      chunk_size = 1024,
      print_enabled = False,
      color_enabled = False,
      special_characters = True,
      device_index = 0,
      sample_rate = 48000,
      sample_width = 1, # width * 8 = bit depth
      log_aps = True,
      audio_only = False
    ):
    if os.getuid() != 0:
      raise Exception('This module requires root priviledges.')
    super().__init__()
    self.daemon = True
    self.interfaces = []
    ifs = re.split(r'[:;,\.\-_\+| ]', interfaces)
    for i in range(len(ifs)) :
      self.interfaces.append(ifs[i])
    self.qty_channels = len(self.interfaces)
    self.lock = Lock()
    self.sockets = None
    self.writer = None
    self.audifier = None
    self.device_index = device_index
    self.chunk = chunk_size
    self.rate = sample_rate
    self.width = sample_width
    self.print_enabled = print_enabled
    self.colorEnabled = color_enabled
    self.ctlEnabled = special_characters
    self.log_aps = log_aps
    self.doRun = False
    self.isStopped = True
    self.isReady = False
    self.audio_only = audio_only
    self.excludedChars = [1,2,3,4,5,6,7,8,9,11,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,155,255]
    # ^ temporary fix to exclude characters that might mess up the console output.
    # https://www.asciitable.com/
    # https://serverfault.com/questions/189520/which-characters-if-catd-will-mess-up-my-terminal-and-make-a-ton-of-noise

    logging.debug(f"DEVICE: {self.device_index}")
    logging.debug(f"interfaces: {self.interfaces}")
    logging.debug(f"qty_channels: {self.qty_channels}")
    logging.debug(f"chunk_size : {self.chunk}")
    logging.debug(f"SAMPLE RATE: {self.rate}")
    logging.debug(f"BYTES PER SAMPLE: {self.width}")
    logging.debug(f"PRINT: {self.print_enabled}")
    logging.debug(f"COLOR: {self.colorEnabled}")
    logging.debug(f"CONTROL_CHARACTERS: {self.ctlEnabled}")
    logging.debug(f"LOG APs: {self.log_aps}")
    logging.debug(f"audio_only: {self.audio_only}")

  def audify_data_callback(self, in_data, frame_count, time_info, status):
    audioChunk, printQueue = self.sockets.extractFrames(frame_count)
    if self.writer:
      self.writer.queueForPrinting(printQueue)
    return(bytes(audioChunk), pyaudio.paContinue)

  def run(self):
    self.doRun = True
    try:
      self.sockets = Listener(self.interfaces)
      self.sockets.start()
    except Exception as e:
      logging.error('Error starting socket listeners: %s' % repr(e))

    try:
      if not self.audio_only:
        self.writer = Writer(
          qty_channels = self.qty_channels,
          chunk = self.chunk*self.qty_channels,
          color = self.colorEnabled,
          linebreaks = self.ctlEnabled,
          enabled = self.print_enabled
        )
        self.writer.start()
    except Exception as e:
      logging.error('Error starting console writers: %s' % repr(e))

    # spin up the audio playback engine
    try:
      self.audifier = Audifier(
        qty_channels = self.qty_channels,
        width = self.width,
        rate = self.rate,
        chunk = self.chunk,
        device_index = self.device_index,
        callback = self.audify_data_callback
      )
      self.audifier.start()
    except Exception as e:
      logging.error('Error starting audifiers: %s' % prer(e))

    self.isStopped = False
    self.isReady = True
  
    while self.doRun:
        sleep(0.1)
    self.isStopped = True

  def stop(self):
    self.doRun = False

    while not self.isStopped:
      sleep(0.01)

    if not self.audio_only:
      try:
        logging.info('Stopping Writer...')
        if self.writer.color:
          self.writer.stop()
          # print('\x1b[0m',end='')
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

  def get_writer_state(self):
    if self.writer:
      return self.writer.getState()

# Listener
# A socket based packet sniffer. Main loop will check sockets for data and grab what's there,
# storing in a buffer to be extracted later. chunk should be a relatively small power of two.
# Until I can figure out a way to tinker with the sockets and set appropriate permissions, this
# is what requires running the script as root.

class Listener(Thread):
  def __init__(self, interfaces, chunk=4096, log_aps=True):
    super().__init__()
    self.daemon = True
    self.lock = Lock()
    self.interfaces = interfaces
    self.chunk = chunk # used to fine tune how much is "grabbed" from the socket
    self.sockets = self.initSockets()
    self.buffers = self.initBuffers() # data will be into and out of the buffer(s)
    self.doRun = False # flag to run main loop & help w/ smooth shutdown of thread
    self.APs = {}
    self.log_aps = log_aps
    self.buffer_size_limit = 1048576

  def initSockets(self):
    sockets = []
    for interface in self.interfaces:
      # etablishes a RAW socket on the given interface, e.g. eth0. meant to only be read.
      s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(0x0003))
      s.bind((interface,0))
      s.setblocking(False) # non-blocking
      sockets.append(s)
    return sockets

  def initBuffers(self):
    # nothing up my sleeves here...
    buffers = []
    for interface in self.interfaces :
      buffers.append(bytearray())
    return buffers

  def getAPs(self):
    with self.lock:
      return self.APs.copy()

  def analyzePacket(self, pkt):
    AP = {}
    SSID = None
    MAC = None
    try:
      if pkt[25] >> 4 & 0b1111 == 0x4 and pkt[25] >> 2 & 0b11 ==0:
        if pkt[49] == 0 and pkt[50] > 0:
          try:
            SSID = pkt[51:51+pkt[50]].decode('utf-8')
            MAC = pkt[29:35].hex()
          except:
            pass
        if not SSID and pkt[54] == 0 and pkt[55] > 0:
          try:
            SSID = pkt[56:56+pkt[55]].decode('utf-8')
            MAC = pkt[29:35].hex()
          except:
            pass
        if SSID:
          return { SSID : { "MAC" : MAC } }  
      else:
        return None
    except:
      return None
      pass

  def addToAPs(self, AP):
    with self.lock:
      for key in AP.keys():
        if not key in self.APs:
          self.APs[key] = {}
          self.APs[key]['MACs'] = [AP[key]['MAC']]
          self.APs[key]['count'] = 1
        else:
          if not AP[key]['MAC'] in self.APs[key]['MACs']:
            self.APs[key]['MACs'].append(AP[key]['MAC'])
          self.APs[key]['count'] += 1

  def readSockets(self):
    for i in range(len(self.sockets)):
      try: # grab a chunk of data from the socket...
        if data := self.sockets[i].recv(65535):
          if self.interfaces[i] in ['wlan1','wlan2'] and self.log_aps:
            if AP := self.analyzePacket(data): # extract APs
              self.addToAPs(AP)
          logging.debug(f"len(buffers[i]) {len(buffers[i])} < self.buffer_size_limit {self.buffer_size_limit}: {len(buffers[i]) < self.buffer_size_limit}")
          if len(buffers[i]) < self.buffer_size_limit:
            with self.lock:
              self.buffers[i].extend(data) # if there's any data there, add it to the buffer
      except: # if there's definitely no data to be read. the socket will throw and exception
        pass

  def extractFrames(self, frames):
    slices = [] # for making the chunk of audio data
    printQueue = [] # for assembling the data into chunks for printing  
    with self.lock:
      for n in range(len(self.buffers)):
        bufferSlice = self.buffers[n][:frames] # grab a slice of data from the buffer
        printQueue.append(bufferSlice) # whatever we got, add it to the print queue. no need to pad
        # this makes sure we return as many frames as requested, by padding with audio "0"
        padded = bufferSlice + bytes([127]) * (frames - len(bufferSlice))
        slices.append(padded)
        self.buffers[n] = self.buffers[n][frames:] # remove the extracted data from the buffer
      if len(self.buffers) == 2 : # interleave the slices to form a stereo chunk
        audioChunk = [ x for y in zip(slices[0], slices[1]) for x in y ]
      elif len(self.buffers) == 1: # marvelous mono
        audioChunk = slices[0]
      else:
        raise Exception("[!] Only supports 1 or two channels/interfaces.")
    return audioChunk, printQueue

  def run(self):
    logging.info('[LISTENER] run()')
    self.doRun = True
    while self.doRun:
      try:
        self.readSockets()
        sleep(0.0001)
      except Exception as e:
        logging.error('[LISTENER] Error executing readSockets(): %s' % repr(e))

  def stop(self):
    logging.info('[LISTENER] stop()')
    self.doRun=False
    try:
      for socket in self.sockets:
        socket.close()
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

  def initBuffers(self):
    self.buffers = []
    for i in range(self.qty_channels):
      self.buffers.append(bytearray())
    return self.buffers

  def queueForPrinting(self, queueData):
    if not self.enabled: return

    with self.lock:
      if len(queueData) != len(self.buffers):
        raise Exception("[!] len(queueData): %s != len(self.buffers): %s" % (len(queueData),len(self.buffers)))
      for i in range(len(self.buffers)):
        if queueData[i]:
          self.buffers[i].extend(queueData[i])

  def printBuffers(self):

    for n in range(len(self.buffers)):
      string = ''
      with self.lock:      

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

        self.buffers[n] = self.buffers[n][size:] # remove chunk from queue. will empty over time if disabled

  def getState(self):
    with self.lock:
      state = {
        'enabled': self.enabled,
        'color': self.color,
        'linebreaks': self.linebreaks,
        'shift': self.shift,
      }
      return state

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

  def ctlCharactersEnable(self, value):
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
  def __init__(self, qty_channels, width=1, rate=44100, chunk=2048, device_index=0, callback=None):
    if not callback:
      raise Exception('Audifier instance requires a callback function. Got: %s' % callback)

    self.qty_channels = qty_channels
    self.width = width
    self.rate = rate
    self.chunk = chunk
    self.device_index = device_index
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
    #     output_device=self.device_index,
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
      output_device_index = self.device_index,
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
