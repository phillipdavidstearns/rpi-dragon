# rpi-dragon



## Installation

1. `$ sudo apt-get update && sudo apt-get install git portaudio19-dev python3-dev`
1. `$ git clone https://github.com/phillipdavidstearns/rpi-dragon.git`
1. `$ sudo python3 -m pip install -e ./rpi-dragon`

## Usage

```python
from rpi_dragon import Dragon

# setup
dragon = Dragon(
	interfaces = 'eth0,wlan0', # specify network devices by name,
  chunk_size = 1024, # sets the number of bytes for print/audio output buffer
  print_enabled = False, # enables/disables printing of data to the console
  color_enabled = False, # enables/disables colorizing of characters
  special_characters = True, # enables/disables printing of line break characters
  device_index = 0, # sets the audio output device
  sample_rate = 48000, # audio sampling rate
  sample_width = 1, # width * 8 = bit depth
  log_aps = True, # enables/disables loggin access points from probe requests
  audio_only = False # completely disables console output
)

dragon.start()

# It's recommended to create a wait loop to allow Dragon to finish starting up
while not dragon.isReady:
	logging.warning('Dragon Not Ready Yet!')
	time.sleep(1)

print('dragon.get_writer_state(): %s' % repr(dragon.get_writer_state))

dragon.stop()

def callback(in_data, frame_count, time_info, status):
	data = []
	for i in range(frame_count):
		data.append(random.randint(0,255))
	return(bytes(data), pyaudio.paContinue)
```
