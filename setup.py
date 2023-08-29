import setuptools

__project__ = "Dragon"
__version__ = "0.0.1"
__description__ = "A class designed to sniff network packets and output them as console text and audio on a Raspberry Pi."
__packages__ = ["Dragon", "pyaudio", "logging", "os", "sys", "socket", "re", "threading", "time"]

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name=__project__,
    version=__version__,
    description=__description__,
    author="Phillip David Stearns",
    author_email="phil@phillipstearns.com",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/phillipdavidstearns/rpi-dragon",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
    ],
    python_requires='>=3.6',
    install_requires=['pyaudio'],
)
