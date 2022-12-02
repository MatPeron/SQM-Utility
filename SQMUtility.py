#!/usr/bin/python

import sys
import logging

LOG_FILENAME = '/opt/SQM/errors.log'
logging.basicConfig(filename=LOG_FILENAME, format="%(asctime)s %(message)s", filemode="w")
logger = logging.getLogger("sqm")
logger.setLevel(logging.DEBUG)

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_exception

import socket
import subprocess
import time
import os
import numpy as np

from skyfield.api import N, E, wgs84, load
from skyfield import almanac

class Timer:    
    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.end = time.perf_counter()
        self.CPUTime = self.end-self.start
        
    def getTime(self):
        return time.perf_counter()-self.start

class SQM_LE:

    def __init__(self, latitude, longitude, elevation, utcDelta=+2, daylightSaving=True, ephemerisFile="/opt/SQM/de421.bsp"):
        
        self.setConnection()
        self.setObservatory(latitude, longitude, elevation, ephemerisFile)
        self.utcDelta = (utcDelta-int(daylightSaving))/24
        
    def setConnection(self, timeout=60):
    
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        
        if hasattr(socket, "SO_BROADCAST"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self.socket.sendto(bytes.fromhex("000000f6"), ("255.255.255.255", 30718))
        
        with Timer() as t:
            while t.getTime()<timeout:
                try:
                    buf, addr = self.socket.recvfrom(30)
                    
                    if hex(buf[3])=="0xf7":
                        self.MAC = ":".join("{:02x}".format(byte) for byte in buf[24:])
                        self.IP = addr[0]
                        self.port = 10001
                    
                        print("Buffer received: {}".format(buf))
                        print("MAC address of sender: {}".format(self.MAC))
                        print("IP address of sender: {}".format(self.IP))
                    
                    break
                except Exception as e:
                    print("Warning: SQM may be busy. This is the exception that caused this message:\n{}".format(e))
                    time.sleep(1)
                    
        self.socket.close()
        del self.socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                
        with Timer() as t:
            while t.getTime()<timeout:
                try:
                    self.connect(self.IP, self.port)
                    break
                except Exception as e:
                    print("Warning: connection attempt has failed, this may be a false alarm but here's the exception that raised this message:\n{}".format(e))
                    time.sleep(1)
                        
        _, self.protocol, self.model, self.feature, self.serial = [i.lstrip("0") for i in self.read((b"ix", 38)).replace("\n", "").replace("\r", "").split(",")]

    def setObservatory(self, latitude, longitude, elevation, ephemerisFile):
    
        self.ephemeris = load(ephemerisFile)
        self.timescale = load.timescale()
        print("Queste due righe devono indicare lo stesso orario (UTC):")
        print(" {}".format(self.timescale.now().utc))
        print(" {}".format(time.gmtime(time.time())))
        
        self.sun, self.moon = self.ephemeris["sun"], self.ephemeris["moon"]
        self.observatory = self.ephemeris["earth"]+wgs84.latlon(latitude*N, longitude*E, elevation_m=elevation)
        
    def getSunMoonAltitudeAndPhase(self, now):
        
        apparentSun = self.observatory.at(now).observe(self.sun).apparent()
        apparentMoon = self.observatory.at(now).observe(self.moon).apparent()
        
        sunAltitude, _, _ = apparentSun.altaz()
        moonAltitude, _, _ = apparentMoon.altaz()
        
        moonPhase = apparentMoon.fraction_illuminated(self.sun)
        
        return sunAltitude.degrees, moonAltitude.degrees, moonPhase
        
    def getTwilights(self, startDate, endDate, twilightType=3):
        
        # set type to 1 for astronomical twilight, set it to 2 for nautical twilight, set it to 3 fron civil twilight
        
        # here write some commands to convert startDate and endDate to timescales
        # startDate = timescale.utc(year, month, day)
        
        f = almanac.dark_twilight_day(self.ephemeris, self.observatory.target)
        times, events = almanac.find_discrete(startDate, endDate, f)
        
        ts = times[np.where(events==twilightType)]
        ttt = []
        for t in ts:
            tt = self.getTimescale(year=t.utc.year,
                                   month=t.utc.month,
                                   day=t.utc.day,
                                   hour=t.utc.hour,
                                   minute=t.utc.minute)+self.utcDelta
            ttt.append(tt)
            
        return ttt
    
    def connect(self, IP, port):
    
        self.socket.connect((IP, port))
        
    def reset(self):
    
        isbufferfull = True
        while isbufferfull:
            isbufferfull = bool(self.socket.recv(256))

        self.socket.close()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.connect(self.IP, self.port)
        
    def read(self, request):
        
        command, return_bytes = request
        self.socket.send(command)
        reading = self.socket.recv(return_bytes)
        
        self.reset()
    
        return reading.decode()
        
    @staticmethod
    def nelm(mpsas):
        
        return 7.93-5*np.log10(10**(4.316-(mpsas/5))+1)
    
    def getTimescale(self, year=None, month=None, day=None, hour=12, minute=0, second=0, tomorrow=False):
        
        offset = 0
        if tomorrow:
            offset = 1
        
        if year is None or month is None or day is None:
            now = (self.timescale.now()+offset).utc
            year = now.year
            month = now.month
            day = now.day
    
        timescale = self.timescale.utc(year, month, day, hour, minute, second)
        
        print("Timescale generated:\n{}".format(timescale.utc))
        
        return timescale
    
    def readingSchedule(self, start, stop, interval, timeout):
        
        assert interval>timeout, "Interval argument should be greater than timeout."
        
        print("Beginning reading schedule between {} and {} every {} seconds".format(start.utc, stop.utc, interval))
        
        startdate = "{}{:0>2}{:0>2}".format(start.utc.year, start.utc.month, start.utc.day)
        
        with Timer() as t:
            now = self.timescale.now()+self.utcDelta
            print("Now is: {}".format(now.utc))
            if now.tt<start.tt:
                wait = (start.tt-now.tt)*24*3600
            elif start.tt<now.tt<stop.tt:
                wait = interval-((now.tt-start.tt)*24*3600)%interval
            else:
                raise RuntimeError("Given 'stop' timestamp {} should be a future timestamp!".format(stop.utc))
                
        print("waiting: {} seconds".format(wait))
        time.sleep(wait-t.CPUTime)
        
        while now.tt<=stop.tt:
            with Timer() as t:
                now = self.timescale.now()+self.utcDelta
                date = "{}/{:0>2}/{:0>2}".format(now.utc.year, now.utc.month, now.utc.day)
                hour = "{:0>2}:{:0>2}:{:0>2.0f}".format(now.utc.hour, now.utc.minute, now.utc.second)
                wait = interval-now.utc.second
                
                while t.getTime()<timeout:
                    try:
                        _, mag, _, _, _, temp = [i.lstrip("0")[:-1] for i in self.read((b"rx", 56)).replace(" ", "").replace("\n", "").replace("\r", "").split(",")]
                        nelm = "{:.2f}".format(self.nelm(float(mag)))
                        encOffset = "0.1"
                        solarAlt, lunarAlt, lunarPhase = ["{:.2f}".format(i) for i in self.getSunMoonAltitudeAndPhase(self.timescale.now())]
                        break
                    except:
                        mag, temp, nelm, encOffset, solarAlt, lunarAlt, lunarPhase = "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a"
                        self.reset()
                        pass
                
                print(date,
                    hour,
                    mag,
                    nelm,
                    self.serial,
                    self.protocol,
                    self.model,
                    self.feature,
                    temp,
                    encOffset,
                    solarAlt,
                    lunarAlt,
                    lunarPhase)
                
                writeFile("/opt/SQM/SQM_output/", 
                        "{}-{}.txt".format(startdate, self.serial),
                        "{},{},{},{},{},{},{},{},{},{},{},{},{}\n".format(date,
                                                                           hour,
                                                                           mag,
                                                                           nelm,
                                                                           self.serial,
                                                                           self.protocol,
                                                                           self.model,
                                                                           self.feature,
                                                                           temp,
                                                                           encOffset,
                                                                           solarAlt,
                                                                           lunarAlt,
                                                                           lunarPhase))
            
                try:
                    plotReadings("/opt/SQM/SQM_output/",
                                 "{}-{}.txt".format(startdate, self.serial),
                                 "{:0>2}:{:0>2}:{:0>2.0f}".format(start.utc.hour, start.utc.minute, start.utc.second),
                                 "{:0>2}:{:0>2}:{:0>2.0f}".format(stop.utc.hour, stop.utc.minute, stop.utc.second),
                                 interval)
                    sendFile("/opt/SQM/SQM_output/",
                             "{}-{}_plot.png".format(startdate, self.serial),
                             "/opt/SQM/alo",
                             "sqm",
                             "image")
                except Exception as e:
                    logger.error("Error when trying to plot data and send, here's the exception: {}".format(e))
            
            
            time.sleep(wait-t.CPUTime)
    
        try:
            sendFile("/opt/SQM/SQM_output/",
                     "{}-{}.txt".format(startdate, self.serial),
                     "/opt/SQM/venetostellato",
                     "letture",
                     "lines")
            sendFile("/opt/SQM/SQM_output/",
                     "{}-{}.txt".format(startdate, self.serial),
                     "/opt/SQM/alo",
                     "sqm",
                     "lines")
        except Exception as e:
            logger.error("Error when trying to send data file, here's the exception: {}".format(e))

def writeFile(path, filename, line):

    if not "\n" in line:
        line = line+"\n"
    
    if not os.path.isfile(path+filename):    
        with open(path+filename, "w") as file:
            file.write("#Formato file basato su SQM Reader Pro 3.1.1.0, Autore: Matteo Peron\n")
            file.write("Year/Month/Day,Hour/Minute/Second,MPSAS,NELM,SerialNo,Protocol,Model,Feature,Temp(C),EncOffset,SolarAlt(deg),LunarAlt(deg),LunarPhase\n")
            file.write(line)

        print("creato file di output in {}".format(path+filename))
    else:
        with open(path+filename, "a") as file:
            file.write(line)
 
import matplotlib.pyplot as plt
plt.rcParams["font.size"] = 16
import warnings
warnings.filterwarnings("ignore")

def plotReadings(path, filename, start, stop, interval): 
    
    date, hour, MPSAS = [], [], []
    with open(path+filename, "r") as file:
        i = 0
        for line in file:
            if i<2:
                i += 1
                continue
            
            data = line.split(",")
            date.append(data[0])
            hour.append(data[1])
            
            if data[2]=="n/a":
                MPSAS.append(np.nan)
            else:
                MPSAS.append(float(data[2]))
                
    toSeconds = lambda hms: sum([int(i)*m for i,m in zip(hms.split(":"), [3600, 60, 0])])
    
    x = []
    for hms in hour:
        x.append((toSeconds(hms)-toSeconds(start))%(24*3600))
        
    xlim = (0, (toSeconds(stop)-toSeconds(start))%(24*3600))
    nPoints = (toSeconds(stop)-toSeconds(start))%(24*3600)//interval
    
    fig = plt.figure(figsize=(16, 10))
    
    ax = fig.add_subplot(111)
    ax.plot(x, MPSAS, marker="o", ms=10, mfc="none", mec="k", lw=0.5)
    
    mxticks, mxticklabels = [], []
    Mxticks, Mxticklabels = [], []
    for i in range(len(hour)):
        if not i%(nPoints//10):
            Mxticks.append(x[i])
            Mxticklabels.append(hour[i])
        else:
            mxticks.append(x[i])
            mxticklabels.append("")
            
    logger.info(Mxticklabels)
        
    ax.set_xticks(Mxticks, Mxticklabels)
    ax.set_xticks(mxticks, mxticklabels, minor=True)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
    ax.set_xlim(-0.01*xlim[-1], 1.01*xlim[-1])
    
    ax.set_xlabel("ora [UTC+2]")
    ax.set_ylabel(r"Brillanza cielo [$mag/arcsec^2$]")
    ax.grid(which="both", linestyle=":", alpha=0.5)
    
    ax.tick_params(axis="both", which='both', top=True, bottom=True, left=True, right=True, direction="in")
    ax.tick_params(axis="both", which="major", length=10)
    ax.tick_params(axis="both", which="minor", length=4)
    
    fig.suptitle("Letture SQM Osservatorio Astronomico \"Parco della Lessinia\" - {}".format(date[0]))
    fig.tight_layout()
        
    fig.savefig(path+filename.split(".")[0]+"_plot.png", dpi=200)
    plt.close("all")
    

from ftplib import FTP
import pickle

def sendFile(path, filename, credentials, cwd, type):

    c = pickle.load(open(credentials, "rb"))
 
    with FTP(host=c["host"], user=c["user"], passwd=c["passwd"], encoding="latin-1") as ftp:
        ftp.cwd(cwd)
        with open(path+filename, "rb") as file:
            if type=="lines":
                ftp.storlines("STOR {}".format(filename), file)
            if type=="image":
                ftp.storbinary("STOR {}".format(filename), file)
