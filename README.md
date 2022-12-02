# SQM-Utility
A python code to interface and read from the [Unihedron's SQM-LE](http://unihedron.com/projects/sqm-le/) device. This sensor is used to monitor sky brightness and is generally used to track light pollution. You can access the sensor data I use this program for at the website https://www.astrofililessiniaorientale.it/sky-quality-meter/.

The code uses the `skyfield` and `numpy` python packages to compute times and ephemeris of the Sun and Moon. The built-in `socket` package is used to interface with the ethernet card on the sensor. The code is still set up for the sensor I manage, but it may be useful to write new codes that aim at reading from these devices.

Documentation is being worked on.
