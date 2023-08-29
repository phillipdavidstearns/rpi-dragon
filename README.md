# rpi-dragon



## Installation

1. `$ sudo apt-get update && sudo apt-get install git python3-pip python3-pyaudio python3-decouple`
1. `$ git clone https://github.com/phillipdavidstearns/rpi-dragon.git`
1. `$ sudo python3 -m pip install -e ./rpi-dragon`

## Usage

```python
import Dragon

# setup
INTERFACES=['eth0,wlan0']

dragon = Dragon(
	INTERFACES,
	CHUNK=1024, #sets the number of bytes for print/audio output
	PRINT=False, #enables/disables printing of data to the console
	COLOR=False, #enables/disables colorizing of characters
	CONTROL_CHARACTERS=True, #enables/disables printing of line break characters
	DEVICE=0, #sets the audio output device
	RATE=44100, #audio sampling rate
	WIDTH=1, #size in bytes of the audio sample
	LOGAPS=True #enables/disables loggin access points from probe requests
)

dragon.start()

# It's recommended to create a wait loop to allow Dragon to finish starting up
while not dragon.isReady:
	logging.warning('Dragon Not Ready Yet!')
	time.sleep(1)

print('dragon.get_writer_state(): %s' % repr(dragon.get_writer_state))

dragon.stop()
```
