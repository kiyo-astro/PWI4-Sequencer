#-----------------------------------------------------------------------------------------------#
# PWI4 Sequencer for SSDL BULL's-eye                                                            #
# Developed by Kiyoaki Okudaira * Kyushu University / IAU-CPS SatHub                            #
#-----------------------------------------------------------------------------------------------#
# coding 2025.07.08: 1st coding (ver 1.0.0)                                                     #
# bugfix 2025.07.10: File not found error when failed to solve at SharpCap (ver 1.0.1)          #
# update 2025.07.19: Shut down sequence and altitude limitation supported (ver 1.0.2)           #
# bugfix 2025.07.21: Syntax error display when unsupported sequence is included (ver 1.0.3)     #
# bugfix 2025.07.29: Unabale to delete cash files bug fixed (ver 1.0.4)                         #
# bugfix 2026.03.23: Sequence file encoding type error fixed (ver 1.0.5)                        #
# bugfix 2026.04.07: Syntax error when receiving negative DEC value fixed (ver 1.0.6)           #
# update 2026.04.28: GUI support and sequence file editor (ver 2.0.0)                           #
# update 2026.05.04: Internal update function (ver 2.0.1)                                       #
#-----------------------------------------------------------------------------------------------#

#-----------------------------------------------------------------------------------------------#
# VERSION                                                                                       #
#-----------------------------------------------------------------------------------------------#
version = "2.0.1"
version_number = 2026050420100

#-----------------------------------------------------------------------------------------------#
# OPTIONS                                                                                       #
#-----------------------------------------------------------------------------------------------#


#-----------------------------------------------------------------------------------------------#
# IMPORT                                                                                        #
#-----------------------------------------------------------------------------------------------#
import json
import os
import queue
import threading
import time
import traceback
import shutil
import tempfile
import subprocess
import urllib.request
import ssl
import zipfile

try:
    import certifi
except Exception:
    certifi = None
from dataclasses import dataclass
from datetime import datetime
from os import path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import sys

from PIL import Image, ImageTk

APP_NAME = "PWI4 Sequencer for SSDL BULL\'s-eye"
COPYRIGHT_TEXT = "Copyright (c) 2026 Kiyoaki Okudaira - Kyushu University / IAU-CPS SatHub"

UPDATE_VERSION_URL = "https://github.com/kiyo-astro/PWI4-Sequencer/raw/refs/heads/main/dist/version_check.txt"
UPDATE_DETAIL_URL = "https://github.com/kiyo-astro/PWI4-Sequencer/raw/refs/heads/main/dist/update_detail.txt"
UPDATE_ZIP_URL = "https://github.com/kiyo-astro/PWI4-Sequencer/raw/refs/heads/main/dist/PWI4%20Sequencer.zip"

if sys.platform.startswith("win"):
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

#-----------------------------------------------------------------------------------------------#
# Path settings: works both in normal Python and PyInstaller builds.                            #
#-----------------------------------------------------------------------------------------------#
def get_base_path() -> str:
    if getattr(sys, "frozen", False):
        return path.abspath(path.dirname(sys.executable))
    return path.abspath(path.dirname(__file__))

appPATH = get_base_path() + "/"
scscript_PATH = appPATH + "SharpCap sequence/"
readme_PATH = appPATH + "README.txt"
preference_PATH = appPATH + "_internal/preferences/"
src_PATH = appPATH + "_internal/src/"


def parse_version_number(text) -> int:
    """Extract an integer build/version number from a text response."""
    for token in str(text).replace("\r", "\n").split():
        cleaned = "".join(ch for ch in token if ch.isdigit())
        if cleaned:
            return int(cleaned)
    raise ValueError(f"No numeric version number found in: {text!r}")


def get_https_ssl_context():
    """Return an SSL context that works in Windows/PyInstaller environments.

    Some Windows builds cannot find a local CA certificate store, which causes
    urllib to raise CERTIFICATE_VERIFY_FAILED.  When certifi is bundled with
    the app, this function explicitly points urllib at certifi's CA bundle.
    """
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


def open_url_with_ssl_fallback(req, timeout: int):
    """Open a HTTPS request, retrying with certifi if the default CA lookup fails."""
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", None)
        is_ssl_error = isinstance(reason, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(e)
        if not is_ssl_error:
            raise
        # Retry using certifi's CA bundle.  This fixes most Windows/PyInstaller
        # environments where Python cannot locate the OS certificate store.
        if certifi is None:
            raise RuntimeError(
                "SSL certificate verification failed and the certifi package is not available. "
                "Install/bundle certifi, or include certifi in the PyInstaller build."
            ) from e
        return urllib.request.urlopen(req, timeout=timeout, context=get_https_ssl_context())


def read_url_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{version}"})
    with open_url_with_ssl_fallback(req, timeout=timeout) as res:
        data = res.read()
    return data.decode("utf-8_sig", errors="replace").strip()


def download_file(url: str, dst: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{version}"})
    with open_url_with_ssl_fallback(req, timeout=timeout) as res, open(dst, "wb") as f:
        shutil.copyfileobj(res, f)


def find_update_payload_root(extract_dir: str) -> str:
    """Return the directory that should be copied over appPATH after extracting the update zip."""
    entries = [path.join(extract_dir, name) for name in os.listdir(extract_dir)]
    dirs = [entry for entry in entries if path.isdir(entry)]
    files = [entry for entry in entries if path.isfile(entry)]

    # Case 1: zip contains a single top-level folder.
    if len(dirs) == 1 and not files:
        return dirs[0]

    # Case 2: zip contains a dist folder.
    for d in dirs:
        if path.basename(d).lower() == "dist":
            return d

    # Case 3: zip contents are already the application root.
    return extract_dir


def quote_bat(value: str) -> str:
    return str(value).replace('"', '""')

#-----------------------------------------------------------------------------------------------#
# Optional BULL's EYE dependencies.                                                             #
#-----------------------------------------------------------------------------------------------#
try:
    from config.pwi4_client import PWI4
    from config import astroKUBO_lib
except Exception:
    PWI4 = None
    astroKUBO_lib = None

#-----------------------------------------------------------------------------------------------#
# Utilities                                                                                     #
#-----------------------------------------------------------------------------------------------#
def play_sound(sound_path):
    if not sys.platform.startswith("win"):
        return
    try:
        import winsound
        if path.exists(sound_path):
            winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception as e:
        print("Sound error:", e)


def play_notification_sound():
    play_sound(src_PATH + "sound/win98 ding.wav")

def play_alert_sound():
    play_sound(src_PATH + "sound/win98 alert.wav")

def play_complete_sound():
    play_sound(src_PATH + "sound/zelda rest.wav")

def play_end_sound():
    play_sound(src_PATH + "sound/zelda end.wav")

def hms2hours(ra_hms: str) -> float:
    return int(ra_hms[0:2]) + float(ra_hms[3:5]) / 60 + float(ra_hms[6:]) / 3600


def dms2deg(dec_dms: str) -> float:
    dec_dms = dec_dms.replace("−", "-")
    sign = -1 if dec_dms.startswith("-") else 1
    dec_dms = dec_dms.lstrip("+-")
    d, m, s = dec_dms.split(":")
    return sign * (int(d) + float(m) / 60 + float(s) / 3600)


def normalize_line(line: str) -> str:
    return " ".join(line.strip().split())


def is_executable_sequence(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def format_sequence_time_value(value: str) -> str:
    value = value.strip()
    upper = value.upper()
    if upper in {"ASAP", "FALSE"}:
        return upper
    if upper == "ENTER":
        return "Input"
    if upper.startswith("ALT="):
        alt = value.split("=", 1)[1]
        return f"El < {alt} deg"
    try:
        dt = datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return value


def sequence_schedule_label(line: str) -> str:
    stripped = normalize_line(line)
    if not is_executable_sequence(stripped):
        return ""
    parts = stripped.split()
    if not parts:
        return ""
    cmd = parts[0]
    try:
        if cmd == "WAITUNTIL" and len(parts) >= 2:
            return format_sequence_time_value(parts[1])
        if cmd == "WAITALTBELOW" and len(parts) >= 2:
            return f"El < {parts[1]} deg"
        if cmd == "WAITENTER":
            return "Input"
        if cmd in {"GOTORADEC", "GOTOAPPARENTRADEC", "GOTOALTAZ"} and len(parts) >= 4:
            at = parts[3].split("=", 1)[1]
            return format_sequence_time_value(at)
        if cmd == "TRACKSAT" and len(parts) >= 3:
            from_value = parts[2].split("=", 1)[1]
            return format_sequence_time_value(from_value)
        if cmd == "SCSOLVEANDSYNC":
            return "Input"
        return "ASAP"
    except Exception:
        return "?"


def display_sequence_with_time(line: str) -> str:
    stripped = line.strip()
    if not is_executable_sequence(stripped):
        return "-"
    return f"[{sequence_schedule_label(stripped)}] {normalize_line(stripped)}"


def executable_indices(lines):
    return [i for i, line in enumerate(lines) if is_executable_sequence(line)]


@dataclass
class BlockSpec:
    label: str
    command: str
    fields: tuple
    builder: callable


BLOCKS = [
    BlockSpec("CONNECTPWI4", "CONNECTPWI4", (), lambda v: "CONNECTPWI4"),
    BlockSpec("STARTPWI4", "STARTPWI4", (), lambda v: "STARTPWI4"),
    BlockSpec("QUITPWI4", "QUITPWI4", (), lambda v: "QUITPWI4"),
    BlockSpec("WAITUNTIL", "WAITUNTIL", (("time", "YYYY-MM-DDThh:mm:ss", ""),), lambda v: f"WAITUNTIL {v['time']}"),
    BlockSpec("WAITALTBELOW", "WAITALTBELOW", (("alt", "Altitude deg", "15.0"),), lambda v: f"WAITALTBELOW {v['alt']}"),
    BlockSpec("WAITENTER", "WAITENTER", (), lambda v: "WAITENTER"),
    BlockSpec("GOTORADEC", "GOTORADEC", (("ra", "RA hh:mm:ss", "20:47:55.0"), ("dec", "DEC ±dd:mm:ss", "+10:22:31.8"), ("at", "AT time / ASAP / ENTER", "ASAP")), lambda v: f"GOTORADEC RA={v['ra']} DEC={v['dec']} AT={v['at']}"),
    BlockSpec("GOTOAPPARENTRADEC", "GOTOAPPARENTRADEC", (("ra", "RA hh:mm:ss", "20:47:55.0"), ("dec", "DEC ±dd:mm:ss", "+10:22:31.8"), ("at", "AT time / ASAP / ENTER", "ASAP")), lambda v: f"GOTOAPPARENTRADEC RA={v['ra']} DEC={v['dec']} AT={v['at']}"),
    BlockSpec("GOTOALTAZ", "GOTOALTAZ", (("alt", "ALT deg", "45.0"), ("az", "AZ deg", "180.0"), ("at", "AT time / ASAP / ENTER", "ASAP")), lambda v: f"GOTOALTAZ ALT={v['alt']} AZ={v['az']} AT={v['at']}"),
    BlockSpec("TRACKSAT", "TRACKSAT", (("target", "NORAD CAT ID / CUSTOM", "25544"), ("from", "FROM time / ASAP / ENTER", "ASAP"), ("to", "TO time / ALT=deg / ENTER / FALSE", "ALT=15")), lambda v: f"TRACKSAT {v['target']} FROM={v['from']} TO={v['to']}"),
    BlockSpec("ENABLETRACKSTAR", "ENABLETRACKSTAR", (), lambda v: "ENABLETRACKSTAR"),
    BlockSpec("DISABLETRACKSTAR", "DISABLETRACKSTAR", (), lambda v: "DISABLETRACKSTAR"),
    BlockSpec("STOPMOUNT", "STOPMOUNT", (), lambda v: "STOPMOUNT"),
    BlockSpec("SCSOLVEANDSYNC", "SCSOLVEANDSYNC", (), lambda v: "SCSOLVEANDSYNC"),
    BlockSpec("CONFIGSPACETRACK", "CONFIGSPACETRACK", (("id", "Space-Track ID", ""), ("password", "Password", "")), lambda v: f"CONFIGSPACETRACK ID={v['id']} PASSWORD={v['password']}"),
    BlockSpec("COMMENT", "#", (("text", "Comment", ""),), lambda v: f"# {v['text']}"),
]


class SequenceRunner:
    def __init__(self, log, ask, select_file, state_callback):
        self.log = log
        self.ask = ask
        self.select_file = select_file
        self.state_callback = state_callback
        self.stop_requested = False
        self.pwi4 = None

    def request_stop(self):
        self.stop_requested = True

    def _check_stop(self):
        if self.stop_requested:
            raise KeyboardInterrupt("Sequence terminated by GUI stop button")

    def sleep(self, seconds: float, step: float = 0.2):
        end = time.time() + seconds
        while time.time() < end:
            self._check_stop()
            time.sleep(min(step, max(0, end - time.time())))

    def wait_dt(self, waituntil: str):
        self.log("info", f"   Holding until {waituntil[:19]}")
        target_time = datetime.strptime(waituntil[:19], "%Y-%m-%dT%H:%M:%S")
        wait_time = (target_time - datetime.now()).total_seconds()
        if wait_time > 0:
            self.sleep(wait_time, step=0.5)
        self.log("info", "   Done")

    def wait_alt(self, alt: str):
        self.log("info", f"   Holding until Target Altitude goes below {alt} deg")
        altitude_degs_former = -90
        self.sleep(1)
        while True:
            self._check_stop()
            status = self.pwi4.status()
            altitude_degs = status.mount.altitude_degs
            if altitude_degs < float(alt) and altitude_degs < altitude_degs_former:
                break
            altitude_degs_former = altitude_degs
            self.sleep(1)
        self.log("info", "   Done")

    def wait_enter(self, message="Enter to run next sequence"):
        self.log("prompt", f" * {message} :")
        ok = self.ask(message)
        if not ok:
            raise KeyboardInterrupt("User canceled prompt")

    def connect_pwi4_object(self):
        if PWI4 is None:
            raise RuntimeError("PWI 4 client file is broken or missing. Re-install PWI4 Sequencer again.")
        while True:
            self._check_stop()
            try:
                self.pwi4 = PWI4()
                self.pwi4.status()
                break
            except Exception:
                self.log("error", " X ERROR : PWI4 Application is not opened")
                ok = self.ask("Open PWI4 and press OK","alert")
                if not ok:
                    raise KeyboardInterrupt("PWI4 connection canceled")

    def connect_to_mount(self):
        self.log("info", "   Connecting to mount...")
        self.pwi4.mount_connect()
        while not self.pwi4.status().mount.is_connected:
            self.sleep(1)
        self.log("info", "   Done")

    def disconnect_to_mount(self):
        self.log("info", "   Disconnecting to mount...")
        self.pwi4.mount_disconnect()
        while self.pwi4.status().mount.is_connected:
            self.sleep(1)
        self.log("info", "   Done")

    def enable_motors(self):
        self.log("info", "   Enabling motors...")
        self.pwi4.mount_enable(0)
        self.pwi4.mount_enable(1)
        while True:
            self._check_stop()
            status = self.pwi4.status()
            if status.mount.axis0.is_enabled and status.mount.axis1.is_enabled:
                break
            self.sleep(1)
        self.log("info", "   Done")

    def disable_motors(self):
        self.log("info", "   Disabling motors...")
        self.pwi4.mount_disable(0)
        self.pwi4.mount_disable(1)
        while True:
            self._check_stop()
            status = self.pwi4.status()
            if not status.mount.axis0.is_enabled and not status.mount.axis1.is_enabled:
                break
            self.sleep(1)
        self.log("info", "   Done")

    def find_home(self):
        self.log("info", "   Finding home...")
        self.pwi4.mount_find_home()
        last_axis0 = -99999
        last_axis1 = -99999
        while True:
            self._check_stop()
            status = self.pwi4.status()
            d0 = status.mount.axis0.position_degs - last_axis0
            d1 = status.mount.axis1.position_degs - last_axis1
            if abs(d0) < 0.001 and abs(d1) < 0.001:
                break
            last_axis0 = status.mount.axis0.position_degs
            last_axis1 = status.mount.axis1.position_degs
            self.sleep(1)
        self.log("info", "   Done")

    def start_pwi4(self):
        self.log("info", "   Starting up PWI4...")
        self.connect_to_mount()
        self.enable_motors()
        self.log("warning", " ! WARNING : Remove telescope cover and Set a sensor with telescope")
        self.wait_enter("Remove telescope cover, set a sensor, then press OK to start home mount")
        self.find_home()
        self.log("info", "   Done All start up process")

    def quit_pwi4(self):
        self.log("info", "   Shutting down PWI4...")
        self.find_home()
        self.log("warning", " ! WARNING : Set telescope cover and Remove a sensor from telescope")
        self.wait_enter("Set telescope cover, remove sensor, then press OK to disable motors")
        self.disable_motors()
        self.disconnect_to_mount()
        self.log("info", "   Done All shut down process")
        self.log("warning", " ! WARNING : DO NOT FORGET TO SHUT DOWN MASTER POWER OF TELESCOPE!!!")

    def get_TLE(self, norad_id: str):
        if astroKUBO_lib is None:
            raise RuntimeError("config.astroKUBO_lib could not be imported.")
        self.log("info", "   Downloading TLE...")
        status_code = None
        tle_source = None
        while status_code != 200:
            self._check_stop()
            try:
                with open(preference_PATH + "spacetrack-config.json", "r", encoding="utf-8") as f:
                    config = json.load(f)
                user_id = config["identity"]
                password = config["password"]
                tle_source = "Space-Track.org"
            except Exception:
                tle_source = "CelesTrak.org"
            if tle_source == "Space-Track.org":
                status_code, tle_result = astroKUBO_lib.space_track.get_recent_TLE(norad_id, user_id, password)
                if status_code != 200:
                    tle_source = "CelesTrak.org"
            if tle_source == "CelesTrak.org":
                status_code, tle_result = astroKUBO_lib.celes_trak.get_recent_TLE(norad_id)
            if status_code != 200:
                self.sleep(1)
        try:
            lines = tle_result.split("\n")
            tle1, tle2, tle3 = lines[0], lines[1], lines[2]
            epoch = astroKUBO_lib.tle_reader.parse_tle_epoch(tle2)
            self.log("info", f"   Done")
            self.log("info", f"   Downloaded TLE is shown below (Epoch {epoch} | Source {tle_source})")
            self.log("info", "   ---------------------------------------------------------------------")
            self.log("info", "   " + tle1)
            self.log("info", "   " + tle2)
            self.log("info", "   " + tle3)
            self.log("info", "   ---------------------------------------------------------------------")
            return tle1, tle2, tle3
        except Exception:
            return False, False, False

    def parse_TLE(self):
        filename = self.select_file(
            title="Select TLE file",
            filetypes=[("TLE/Text files", "*.txt *.TXT *.tle *.TLE"), ("All files", "*.*")],
            initialdir=appPATH,
        )
        if not filename:
            return False, False, False
        self.log("info", "   Reading TLE file...")
        try:
            with open(filename, encoding="utf-8") as f:
                tles = f.read().splitlines()
            tle1, tle2, tle3 = tles[0], tles[1], tles[2]
            epoch = astroKUBO_lib.tle_reader.parse_tle_epoch(tle2) if astroKUBO_lib else "unknown"
            self.log("info", f"   Done")
            self.log("info", f"   TLE is shown below (Epoch {epoch})")
            self.log("info", "   ---------------------------------------------------------------------")
            self.log("info", "   " + tle1)
            self.log("info", "   " + tle2)
            self.log("info", "   " + tle3)
            self.log("info", "   ---------------------------------------------------------------------")
            return tle1, tle2, tle3
        except Exception:
            return False, False, False

    def track_sat(self, tle1, tle2, tle3):
        self.log("info", "   Slewing to satellite...")
        self.pwi4.mount_follow_tle(tle1, tle2, tle3)
        self.sleep(1)
        while True:
            self._check_stop()
            status = self.pwi4.status()
            dist0 = status.mount.axis0.dist_to_target_arcsec
            dist1 = status.mount.axis1.dist_to_target_arcsec
            self.log("info", "   Distance to target: %.1f x %.1f arcsec" % (dist0, dist1))
            if abs(dist0) < 2 and abs(dist1) < 2:
                self.log("info", "   Arrived at target")
                self.sleep(1)
                break
            self.sleep(0.2)
        self.log("info", "   Tracking satellite")

    def goto_radec_apparent(self, ra, dec):
        self.log("info", f"   Slewing to RA={ra}, DEC={dec} (APPARENT)")
        self.pwi4.mount_goto_ra_dec_apparent(hms2hours(ra), dms2deg(dec))
        self._wait_until_arrived()
        self.log("info", "   Done")

    def goto_radec(self, ra, dec):
        self.log("info", f"   Slewing to RA={ra}, DEC={dec} (J2000)")
        self.pwi4.mount_goto_ra_dec_j2000(hms2hours(ra), dms2deg(dec))
        self._wait_until_arrived()
        self.log("info", "   Done")

    def goto_altaz(self, alt, az):
        self.log("info", f"   Slewing to ALT={alt}, AZ={az}")
        self.pwi4.mount_goto_alt_az(float(alt), float(az))
        self._wait_until_arrived()
        self.log("info", "   Done")

    def _wait_until_arrived(self):
        self.sleep(1)
        while True:
            self._check_stop()
            status = self.pwi4.status()
            dist0 = status.mount.axis0.dist_to_target_arcsec
            dist1 = status.mount.axis1.dist_to_target_arcsec
            self.log("info", "   Distance to target: %.1f x %.1f arcsec" % (dist0, dist1))
            if abs(dist0) < 2 and abs(dist1) < 2:
                self.log("info", "   Arrived at target")
                break
            self.sleep(0.2)

    def sc_solveandsync(self):
        self.wait_enter("Run plate solve script at SharpCap, then press OK")
        try:
            fn = f"{scscript_PATH}/tmp/tmp.fits.CameraSettings.txt"
            with open(fn, "r", encoding="utf-8_sig") as txt_open:
                sc_settings = sum([part for part in (element.split(sep="=") for element in txt_open.read().split("\n"))], [])
            idx = sc_settings.index("Plate solve result was RA")
            ra = sc_settings[idx + 1].split(",")[0]
            dec = sc_settings[idx + 2].split(",")[0]
            self.log("info", f"   Solved RA={ra}, DEC={dec}")
            ok = self.ask("Do you really want to sync at this coordinate?")
            if ok:
                self.pwi4.mount_model_add_point(hms2hours(ra), dms2deg(dec))
                self.log("info", "   Done")
        except FileNotFoundError:
            play_alert_sound()
            self.log("error", " X ERROR : SharpCap capture setting file is undefined")
        except Exception:
            play_alert_sound()
            self.log("error", " X ERROR : Plate solve result is not found")

    def set_spacetrack(self, user_id, password):
        os.makedirs(preference_PATH, exist_ok=True)
        with open(preference_PATH + "spacetrack-config.json", "w", encoding="utf-8") as f:
            json.dump({"identity": user_id, "password": password}, f, indent=4)
        self.log("info", f"   Set Space-Track.org user_id : {user_id} and password : {'*' * len(password)}")

    def run_line(self, original_sequence: str):
        line = original_sequence.strip()
        if not line or line.startswith("#"):
            return
        seq = line.split(" ")
        cmd = seq[0]
        self.log("start", f"-> RUNNING SEQUENCE {line}")
        if cmd == "CONNECTPWI4":
            self.connect_pwi4_object()
        elif cmd == "STARTPWI4":
            self.start_pwi4()
        elif cmd == "QUITPWI4":
            self.quit_pwi4()
        elif cmd == "WAITUNTIL":
            self.wait_dt(seq[1])
        elif cmd == "WAITALTBELOW":
            self.wait_alt(seq[1])
        elif cmd == "WAITENTER":
            self.wait_enter()
        elif cmd == "GOTOAPPARENTRADEC":
            at = seq[3].split("=", 1)[1]
            if at == "ENTER":
                self.wait_enter()
            elif at != "ASAP":
                self.wait_dt(at)
            self.goto_radec_apparent(seq[1].split("=", 1)[1], seq[2].split("=", 1)[1])
        elif cmd == "GOTORADEC":
            at = seq[3].split("=", 1)[1]
            if at == "ENTER":
                self.wait_enter()
            elif at != "ASAP":
                self.wait_dt(at)
            self.goto_radec(seq[1].split("=", 1)[1], seq[2].split("=", 1)[1])
        elif cmd == "GOTOALTAZ":
            at = seq[3].split("=", 1)[1]
            if at == "ENTER":
                self.wait_enter()
            elif at != "ASAP":
                self.wait_dt(at)
            self.goto_altaz(seq[1].split("=", 1)[1], seq[2].split("=", 1)[1])
        elif cmd == "SCSOLVEANDSYNC":
            self.sc_solveandsync()
        elif cmd == "TRACKSAT":
            if seq[1] == "CUSTOM":
                tle1, tle2, tle3 = self.parse_TLE()
            else:
                tle1, tle2, tle3 = self.get_TLE(seq[1])
            if tle1 is not False:
                from_value = seq[2].split("=", 1)[1]
                if from_value == "ENTER":
                    self.wait_enter()
                elif from_value != "ASAP":
                    self.wait_dt(from_value)
                self.track_sat(tle1, tle2, tle3)
                to_token = seq[3]
                to_value = to_token.split("=", 1)[1]
                if to_value.upper() != "FALSE":
                    if to_value.upper().startswith("ALT="):
                        self.wait_alt(to_value.split("=", 1)[1])
                        self.pwi4.mount_stop(); self.log("info", "   Mount stopped")
                    elif to_value.upper() == "ENTER":
                        self.wait_enter()
                        self.pwi4.mount_stop(); self.log("info", "   Mount stopped")
                    else:
                        self.wait_dt(to_value)
                        self.pwi4.mount_stop(); self.log("info", "   Mount stopped")
            else:
                self.log("error", " X ERROR : Invalid TLE format or no TLE data found")
        elif cmd == "ENABLETRACKSTAR":
            self.pwi4.mount_tracking_on(); self.log("info", "   Tracking stars")
        elif cmd == "DISABLETRACKSTAR":
            self.pwi4.mount_tracking_off(); self.log("info", "   Tracking stars stopped")
        elif cmd == "STOPMOUNT":
            self.pwi4.mount_stop(); self.log("info", "   Mount stopped")
        elif cmd == "CONFIGSPACETRACK":
            self.set_spacetrack(seq[1].split("=", 1)[1], seq[2].split("=", 1)[1])
        else:
            raise KeyError(cmd)
        self.log("done", f" □ DONE SEQUENCE {line}")

    def run_sequence(self, lines, filename="untitled"):
        self.stop_requested = False
        self.log("start", f"=> START RUNNING SEQUENCE FILE {filename}")
        for i, line in enumerate(lines):
            original = line.strip()
            if not is_executable_sequence(original):
                continue
            self.state_callback(i, lines)
            self._check_stop()
            try:
                self.run_line(original)
            except KeyboardInterrupt:
                play_end_sound()
                self.log("error", " X Sequence terminated")
                return
            except Exception as exc:
                play_alert_sound()
                self.log("error", f" X ERROR : Sequence \"{original}\" includes unsupported syntax or utility")
                self.log("debug", "   " + str(exc))
        self.state_callback(None, lines)
        play_complete_sound()
        self.log("done", f" ■ FINISHED ALL SEQUENCE {filename}")


class AddBlockDialog(simpledialog.Dialog):
    def __init__(self, parent, initial_text=None):
        self.initial_text = initial_text
        self.result_line = None
        self.vars = {}
        super().__init__(parent, title="Add / Edit Sequence Block")

    def body(self, master):
        ttk.Label(master, text="Block type").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.block_var = tk.StringVar(value=BLOCKS[0].label)
        self.combo = ttk.Combobox(master, textvariable=self.block_var, values=[b.label for b in BLOCKS], state="readonly", width=28)
        self.combo.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        self.combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_fields())
        self.field_frame = ttk.Frame(master)
        self.field_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=6, pady=4)
        self.raw_var = tk.StringVar(value=self.initial_text or "")
        ttk.Label(master, text="Raw command").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(master, textvariable=self.raw_var, width=70).grid(row=2, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(master, text="Use raw command", command=self.use_raw).grid(row=3, column=1, sticky="e", padx=6, pady=4)
        master.columnconfigure(1, weight=1)
        self.refresh_fields()
        if self.initial_text:
            self.guess_initial_block(self.initial_text)
        return self.combo

    def current_spec(self):
        label = self.block_var.get()
        return next(b for b in BLOCKS if b.label == label)

    def refresh_fields(self):
        for w in self.field_frame.winfo_children():
            w.destroy()
        self.vars = {}
        spec = self.current_spec()
        for r, (key, label, default) in enumerate(spec.fields):
            ttk.Label(self.field_frame, text=label).grid(row=r, column=0, sticky="w", padx=4, pady=3)
            var = tk.StringVar(value=default)
            ent = ttk.Entry(self.field_frame, textvariable=var, width=45)
            ent.grid(row=r, column=1, sticky="ew", padx=4, pady=3)
            self.vars[key] = var
        self.field_frame.columnconfigure(1, weight=1)

    def guess_initial_block(self, text):
        parts = text.strip().split()
        if not parts:
            return
        cmd = "COMMENT" if parts[0].startswith("#") else parts[0]
        for b in BLOCKS:
            if b.command == cmd or b.label == cmd:
                self.block_var.set(b.label)
                self.refresh_fields()
                break

    def use_raw(self):
        self.result_line = self.raw_var.get().strip()
        self.ok()

    def apply(self):
        if self.result_line:
            return
        spec = self.current_spec()
        values = {k: var.get().strip() for k, var in self.vars.items()}
        self.result_line = normalize_line(spec.builder(values))

class SplashScreen(tk.Toplevel):
    def __init__(self, parent, duration=3000):
        super().__init__(parent)

        self.overrideredirect(True)  # タイトルバー消す
        self.configure(bg="#1e1e1e")

        scale = float(parent.tk.call("tk", "scaling"))

        w = int(560 * scale)
        h = int(360 * scale)

        ws = self.winfo_screenwidth()
        hs = self.winfo_screenheight()
        x = (ws // 2) - (w // 2)
        y = (hs // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

        # ===== ロゴ =====
        try:
            img = Image.open(src_PATH + "logo/app_icon_full.png")
            img.thumbnail((int(320 * scale), int(160 * scale)), Image.Resampling.LANCZOS)
            self.logo = ImageTk.PhotoImage(img)
            tk.Label(self, image=self.logo, bg="#1e1e1e").pack(pady=(30, 10))
        except Exception as e:
            print("Splash logo error:", e)

        # ===== アプリ名 =====
        tk.Label(
            self,
            text="PWI4 Sequencer for SSDL BULL's-eye",
            fg="#d4d4d4",
            bg="#1e1e1e",
            font=("Segoe UI", 18, "bold")
        ).pack()

        tk.Label(
            self,
            text=f"Version {version} (Build {version_number})",
            fg="#9da5b4",
            bg="#1e1e1e",
            font=("Segoe UI", 10)
        ).pack()

        # ===== コピーライト =====
        tk.Label(
            self,
            text="Copyright (c) 2026 Kiyoaki Okudaira - Kyushu University / IAU-CPS SatHub",
            fg="#9da5b4",
            bg="#1e1e1e",
            font=("Segoe UI", 9)
        ).pack(pady=(10, 20))

        # 指定時間後に閉じる
        self.after(duration, self.destroy)

class SequencerGUI(tk.Tk):
    def __init__(self):
        super().__init__()

        try:
            ico_path = src_PATH + "logo/icon128.ico"
            self.iconbitmap(ico_path)
        except Exception as e:
            print("Window icon error:", e)

        import sys
        if sys.platform.startswith("win"):
            try:
                import ctypes
                user32 = ctypes.windll.user32
                user32.SetProcessDPIAware()
                dpi = user32.GetDpiForSystem()

                scale = dpi / 96.0   # 96dpiが基準
                self.tk.call("tk", "scaling", scale)

            except Exception:
                pass

        self.title(f"{APP_NAME} ver {version}")

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()

        self.geometry(f"{int(sw*0.7)}x{int(sh*0.7)}")

        self.minsize(500, 620)
        self.lines = []
        self.filename = None
        self.runner = None
        self.runner_thread = None
        self.q = queue.Queue()
        self.current_index = None
        self.apply_dark_theme()
        self.build_ui()
        self.after(100, self.process_queue)

    def apply_dark_theme(self):
        """Apply a VS Code-like dark theme to the whole Tk/ttk GUI."""
        self.colors = {
            "bg": "#1e1e1e",
            "panel": "#252526",
            "panel2": "#2d2d30",
            "field": "#1b1b1b",
            "fg": "#d4d4d4",
            "muted": "#9da5b4",
            "border": "#3c3c3c",
            "select": "#094771",
            "select_fg": "#ffffff",
            "button": "#333333",
            "button_active": "#3f3f46",
            "accent": "#007acc",
            "warning": "#dcdcaa",
            "error": "#f48771",
            "success": "#89d185",
            "prompt": "#569cd6",
            "debug": "#808080",
        }
        c = self.colors
        self.configure(bg=c["bg"])

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        default_font = ("Segoe UI", 10)
        heading_font = ("Segoe UI", 10, "bold")

        style.configure(".",
            background=c["bg"],
            foreground=c["fg"],
            fieldbackground=c["field"],
            bordercolor=c["border"],
            darkcolor=c["border"],
            lightcolor=c["border"],
            troughcolor=c["panel2"],
            selectbackground=c["select"],
            selectforeground=c["select_fg"],
            font=default_font,
        )

        style.configure("TFrame", background=c["bg"])
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        style.configure("Muted.TLabel", background=c["bg"], foreground=c["muted"])
        style.configure("Title.TLabel", background=c["bg"], foreground=c["fg"], font=("Segoe UI", 20, "bold"))

        style.configure("TButton",
            background=c["button"],
            foreground=c["fg"],
            bordercolor=c["border"],
            focusthickness=1,
            focuscolor=c["accent"],
            padding=(8, 4),
        )
        style.map("TButton",
            background=[("active", c["button_active"]), ("pressed", c["select"]), ("disabled", c["panel2"])],
            foreground=[("disabled", c["debug"]), ("active", c["select_fg"])],
            bordercolor=[("focus", c["accent"])],
        )

        style.configure("TEntry",
            fieldbackground=c["field"],
            foreground=c["fg"],
            insertcolor=c["fg"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            padding=3,
        )
        style.map("TEntry",
            fieldbackground=[("disabled", c["panel2"]), ("readonly", c["field"])],
            foreground=[("disabled", c["debug"])],
            bordercolor=[("focus", c["accent"])],
        )

        style.configure("TCombobox",
            fieldbackground=c["field"],
            background=c["button"],
            foreground=c["fg"],
            arrowcolor=c["fg"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            padding=3,
        )
        style.map("TCombobox",
            fieldbackground=[("readonly", c["field"]), ("disabled", c["panel2"])],
            foreground=[("readonly", c["fg"]), ("disabled", c["debug"])],
            background=[("active", c["button_active"])],
            arrowcolor=[("disabled", c["debug"])],
            bordercolor=[("focus", c["accent"])],
        )
        self.option_add("*TCombobox*Listbox.background", c["field"])
        self.option_add("*TCombobox*Listbox.foreground", c["fg"])
        self.option_add("*TCombobox*Listbox.selectBackground", c["select"])
        self.option_add("*TCombobox*Listbox.selectForeground", c["select_fg"])

        style.configure("Treeview",
            background=c["field"],
            foreground=c["fg"],
            fieldbackground=c["field"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            rowheight=25,
        )
        style.configure("Treeview.Heading",
            background=c["panel2"],
            foreground=c["fg"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
            font=heading_font,
        )
        style.map("Treeview",
            background=[("selected", c["select"])],
            foreground=[("selected", c["select_fg"])],
        )
        style.map("Treeview.Heading",
            background=[("active", c["button_active"])],
            foreground=[("active", c["select_fg"])],
        )

        style.configure("TLabelframe",
            background=c["bg"],
            foreground=c["fg"],
            bordercolor=c["border"],
            lightcolor=c["border"],
            darkcolor=c["border"],
        )
        style.configure("TLabelframe.Label", background=c["bg"], foreground=c["fg"], font=heading_font)
        style.configure("TPanedwindow", background=c["bg"], sashrelief="flat")
        style.configure("Vertical.TScrollbar", background=c["panel2"], troughcolor=c["bg"], bordercolor=c["border"], arrowcolor=c["fg"])
        style.configure("Horizontal.TScrollbar", background=c["panel2"], troughcolor=c["bg"], bordercolor=c["border"], arrowcolor=c["fg"])

        self.option_add("*background", c["bg"])
        self.option_add("*foreground", c["fg"])
        self.option_add("*activeBackground", c["button_active"])
        self.option_add("*activeForeground", c["select_fg"])
        self.option_add("*selectBackground", c["select"])
        self.option_add("*selectForeground", c["select_fg"])
        self.option_add("*insertBackground", c["fg"])
        self.option_add("*Entry.background", c["field"])
        self.option_add("*Entry.foreground", c["fg"])
        self.option_add("*Text.background", c["field"])
        self.option_add("*Text.foreground", c["fg"])

    def setup_menu(self):
        """Create the application menu bar."""
        menubar = tk.Menu(
            self,
            bg=self.colors["panel"],
            fg=self.colors["fg"],
            activebackground=self.colors["select"],
            activeforeground=self.colors["select_fg"],
            tearoff=False,
        )

        view_menu = tk.Menu(
            menubar,
            tearoff=False,
            bg=self.colors["panel"],
            fg=self.colors["fg"],
            activebackground=self.colors["select"],
            activeforeground=self.colors["select_fg"],
        )
        view_menu.add_command(label="Settings...", command=self.show_settings_dialog)
        view_menu.add_separator()
        view_menu.add_command(label="Check for updates...", command=self.check_for_updates)
        menubar.add_cascade(label="PWI4 Sequencer", menu=view_menu)

        help_menu = tk.Menu(
            menubar,
            tearoff=False,
            bg=self.colors["panel"],
            fg=self.colors["fg"],
            activebackground=self.colors["select"],
            activeforeground=self.colors["select_fg"],
        )
        
        help_menu.add_command(label="Version history", command=self.show_history_dialog)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.show_about_dialog)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)

    def check_for_updates(self):
        """Check GitHub-hosted version_check.txt and ask the user whether to update."""
        # play_notification_sound()
        self.add_log("info", "   Checking for updates...")
        self.config(cursor="watch")

        def worker():
            try:
                latest_text = read_url_text(UPDATE_VERSION_URL)
                latest_number = parse_version_number(latest_text)
                detail_text = ""
                if latest_number > int(version_number):
                    detail_text = read_url_text(UPDATE_DETAIL_URL)
                self.q.put(("update_check_result", True, latest_number, detail_text, None))
            except Exception as e:
                self.q.put(("update_check_result", False, None, "", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def handle_update_check_result(self, ok, latest_number, detail_text, error):
        self.config(cursor="")
        if not ok:
            self.add_log("error", f" X ERROR : Update check failed: {error}")
            self.ask(
                f"Failed to check for updates.\n\nError:\n{error}",
                sound="alert",
                title="Update check failed",
                parent=self,
                mode="ok",
            )
            return

        if latest_number <= int(version_number):
            self.add_log("info", f"   You are using the latest version. Current build: {version_number}, Latest build: {latest_number}")
            self.ask(
                f"You are using the latest version.\n\nCurrent: Version {version} (Build {version_number})\nLatest build: {latest_number}",
                sound="alert",
                title="No updates available",
                parent=self,
                mode="ok",
            )
            return

        detail = detail_text.strip() or "No update details are available."
        msg = (
            f"A new update is available.\n\n"
            f"Current: Version {version} (Build {version_number})\n"
            f"Latest build: {latest_number}\n\n"
            f"Update details:\n{detail}\n\n"
            "Do you want to download and install this update now?\n\n"
            "The application will close after preparing the updater."
        )
        do_update = self.ask(
            msg,
            sound="notification",
            title="Update available",
            parent=self,
            mode="okcancel",
        )
        if do_update:
            self.download_and_prepare_update(latest_number)

    def download_and_prepare_update(self, latest_number):
        """Download update zip, prepare a Windows batch updater, and close the app."""
        self.add_log("info", f"   Downloading update build {latest_number}...")
        self.config(cursor="watch")

        def worker():
            try:
                result = self.prepare_update_files(latest_number)
                self.q.put(("update_prepare_result", True, result, None))
            except Exception as e:
                self.q.put(("update_prepare_result", False, None, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def prepare_update_files(self, latest_number):
        if not sys.platform.startswith("win"):
            raise RuntimeError("The built-in updater is intended for Windows builds only.")

        update_root = tempfile.mkdtemp(prefix="PWI4SequencerUpdate_")
        zip_path = path.join(update_root, "PWI4 Sequencer.zip")
        extract_dir = path.join(update_root, "extracted")
        backup_dir = path.join(update_root, "backup")
        os.makedirs(extract_dir, exist_ok=True)
        os.makedirs(backup_dir, exist_ok=True)

        download_file(UPDATE_ZIP_URL, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        payload_root = find_update_payload_root(extract_dir)

        # Preserve current Space-Track.org account settings.
        current_config = preference_PATH + "spacetrack-config.json"
        backup_config = path.join(backup_dir, "spacetrack-config.json")
        if path.exists(current_config):
            shutil.copy2(current_config, backup_config)

        batch_path = path.join(update_root, "install_update.bat")
        app_dir = appPATH.rstrip("/\\")
        config_dest = path.join(app_dir, "_internal", "preferences", "spacetrack-config.json")
        config_dest_dir = path.dirname(config_dest)
        pid = os.getpid()

        if getattr(sys, "frozen", False):
            restart_command = f'start "" "{quote_bat(sys.executable)}"'
        else:
            restart_command = f'start "" "{quote_bat(sys.executable)}" "{quote_bat(path.abspath(__file__))}"'

        batch_lines = [
            "@echo off",
            "setlocal",
            f'set "APP_DIR={quote_bat(app_dir)}"',
            f'set "SRC_DIR={quote_bat(payload_root)}"',
            f'set "CONFIG_BAK={quote_bat(backup_config)}"',
            f'set "CONFIG_DEST={quote_bat(config_dest)}"',
            f'set "CONFIG_DEST_DIR={quote_bat(config_dest_dir)}"',
            f'echo Updating {APP_NAME} to build {latest_number}...',
            "echo Waiting for the running application to close...",
            ":wait_app",
            f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul',
            "if not errorlevel 1 (",
            "    timeout /t 1 /nobreak >nul",
            "    goto wait_app",
            ")",
            "echo Copying new files...",
            r'xcopy "%SRC_DIR%\*" "%APP_DIR%" /E /H /C /I /Y',
            "if errorlevel 1 (",
            "    echo Update copy reported an error.",
            "    pause",
            "    exit /b 1",
            ")",
            'if exist "%CONFIG_BAK%" (',
            '    if not exist "%CONFIG_DEST_DIR%" mkdir "%CONFIG_DEST_DIR%"',
            '    copy /Y "%CONFIG_BAK%" "%CONFIG_DEST%" >nul',
            ")",
            "echo Update complete.",
            restart_command,
            "endlocal",
            '(goto) 2>nul & del "%~f0"',
        ]
        with open(batch_path, "w", encoding="cp932", errors="replace", newline="\r\n") as f:
            f.write("\r\n".join(batch_lines) + "\r\n")

        return {"batch_path": batch_path, "update_root": update_root, "latest_number": latest_number}

    def handle_update_prepare_result(self, ok, result, error):
        self.config(cursor="")
        if not ok:
            self.add_log("error", f" X ERROR : Failed to prepare update: {error}")
            self.ask(
                f"Failed to download or prepare the update.\n\nError:\n{error}",
                sound="alert",
                title="Update failed",
                parent=self,
                mode="ok",
            )
            return

        self.add_log("done", f"   Update build {result['latest_number']} was downloaded. Closing app and starting installer...")
        proceed = self.ask(
            "The update has been downloaded.\n\nThe application will now close, install the update, and restart automatically.",
            sound="complete",
            title="Ready to update",
            parent=self,
            mode="ok",
        )
        if not proceed:
            return
        subprocess.Popen(
            f'"{result["batch_path"]}"',
            shell=True,
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        self.destroy()

    def show_settings_dialog(self):
        """Edit Space-Track.org account settings saved in preferences/spacetrack-config.json."""
        settings = tk.Toplevel(self)
        settings.title("Settings...")

        try:
            settings.iconbitmap(src_PATH + "logo/icon128.ico")
        except Exception as e:
            print("Settings window icon error:", e)

        settings.configure(bg=self.colors["bg"])
        settings.resizable(False, False)
        settings.transient(self)
        settings.grab_set()

        scale = float(self.tk.call("tk", "scaling"))
        scale = max(1.0, min(scale, 1.8))

        w = int(540 * scale)
        h = int(280 * scale)
        settings.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - (w // 2)
        y = self.winfo_y() + (self.winfo_height() // 2) - (h // 2)
        settings.geometry(f"{w}x{h}+{x}+{y}")

        config_path = preference_PATH + "spacetrack-config.json"
        current_identity = ""
        current_password = ""

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            current_identity = config.get("identity", "")
            current_password = config.get("password", "")
        except FileNotFoundError:
            pass
        except Exception as e:
            play_alert_sound()
            messagebox.showwarning(
                "Settings warning",
                f"Failed to read existing Space-Track.org settings.\n\nError:\n{e}",
                parent=settings,
            )

        container = ttk.Frame(settings, padding=16)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Space-Track.org Account", style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 12)
        )

        ttk.Label(container, text="Identity / Email").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=6)
        identity_var = tk.StringVar(value=current_identity)
        identity_entry = ttk.Entry(container, textvariable=identity_var, width=42)
        identity_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=6)

        ttk.Label(container, text="Password").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=6)
        password_var = tk.StringVar(value=current_password)
        password_entry = ttk.Entry(container, textvariable=password_var, width=42, show="*")
        password_entry.grid(row=2, column=1, sticky="ew", pady=6)

        show_password_var = tk.BooleanVar(value=False)
        def toggle_password():
            password_entry.configure(show="" if show_password_var.get() else "*")
        ttk.Checkbutton(
            container,
            text="Show",
            variable=show_password_var,
            command=toggle_password,
        ).grid(row=2, column=2, sticky="w", padx=(8, 0), pady=6)

        ttk.Label(
            container,
            text="",
            style="Muted.TLabel",
            wraplength=int(500 * scale),
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

        def save_settings():
            identity = identity_var.get().strip()
            password = password_var.get()

            if not identity or not password:
                self.ask(
                    "Identity / Email and Password are required.",
                    sound="alert",
                    title="Settings error",
                    parent=settings,
                    mode="ok",
                )
                return

            try:
                os.makedirs(preference_PATH, exist_ok=True)
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump({"identity": identity, "password": password}, f, indent=4)
                self.ask(
                    "Space-Track.org account settings were saved.",
                    sound="notification",
                    title="Settings saved",
                    parent=settings,
                    mode="ok",
                )
                settings.destroy()
            except Exception as e:
                self.ask(
                    f"Failed to save Space-Track.org settings.\n\nPath:\n{config_path}\n\nError:\n{e}",
                    sound="alert",
                    title="Settings error",
                    parent=settings,
                    mode="ok",
                )

        button_frame = ttk.Frame(container)
        button_frame.grid(row=4, column=0, columnspan=3, sticky="e", pady=(18, 0))
        ttk.Button(button_frame, text="Cancel", command=settings.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(button_frame, text="Save", command=save_settings).pack(side="right")

        container.columnconfigure(1, weight=1)
        identity_entry.focus_set()
        settings.bind("<Return>", lambda _event: save_settings())
        settings.bind("<Escape>", lambda _event: settings.destroy())
        settings.wait_window()

    def show_history_dialog(self):
        """Show appPATH + README.txt in a scrollable Help window."""
        history = tk.Toplevel(self)
        history.title("History")

        try:
            history.iconbitmap(src_PATH + "logo/icon128.ico")
        except Exception as e:
            print("History window icon error:", e)

        history.configure(bg=self.colors["bg"])
        history.transient(self)

        scale = float(self.tk.call("tk", "scaling"))
        scale = max(1.0, min(scale, 1.8))

        w = int(760 * scale)
        h = int(560 * scale)
        history.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - (w // 2)
        y = self.winfo_y() + (self.winfo_height() // 2) - (h // 2)
        history.geometry(f"{w}x{h}+{x}+{y}")
        history.minsize(int(520 * scale), int(360 * scale))

        container = ttk.Frame(history, padding=12)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="History", style="Title.TLabel").pack(anchor="w", pady=(0, 8))

        text_frame = ttk.Frame(container)
        text_frame.pack(fill="both", expand=True)

        y_scroll = ttk.Scrollbar(text_frame, orient="vertical")
        x_scroll = ttk.Scrollbar(text_frame, orient="horizontal")
        text = tk.Text(
            text_frame,
            wrap="none",
            bg=self.colors["field"],
            fg=self.colors["fg"],
            insertbackground=self.colors["fg"],
            selectbackground=self.colors["select"],
            selectforeground=self.colors["select_fg"],
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["accent"],
            font=("Cascadia Mono", 11),
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
        )
        y_scroll.configure(command=text.yview)
        x_scroll.configure(command=text.xview)

        text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

        try:
            with open(readme_PATH, "r", encoding="utf-8_sig") as f:
                content = f.read()
        except FileNotFoundError:
            play_alert_sound()
            content = f"README.txt was not found."
        except Exception as e:
            play_alert_sound()
            content = f"Failed to open README.txt.\n\nError:\n{e}"

        text.insert("1.0", content)
        text.configure(state="disabled")

        bottom = ttk.Frame(container)
        bottom.pack(fill="x", pady=(10, 0))
        # ttk.Label(bottom, text=readme_PATH, style="Muted.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Button(bottom, text="OK", command=history.destroy).pack(side="right")

        history.bind("<Escape>", lambda _event: history.destroy())

    def show_about_dialog(self):
        """Show version information using the same contents as the splash screen."""
        about = tk.Toplevel(self)
        about.title("About")

        try:
            about.iconbitmap(src_PATH + "logo/icon128.ico")
        except Exception as e:
            print("About window icon error:", e)

        about.configure(bg=self.colors["bg"])
        about.resizable(False, False)
        about.transient(self)
        about.grab_set()

        scale = float(self.tk.call("tk", "scaling"))
        scale = max(1.0, min(scale, 1.8))
        
        w = int(560 * scale)
        h = int(360 * scale)
        
        about.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - (w // 2)
        y = self.winfo_y() + (self.winfo_height() // 2) - (h // 2)
        about.geometry(f"{w}x{h}+{x}+{y}")

        container = tk.Frame(about, bg=self.colors["bg"])
        container.pack(fill="both", expand=True, padx=24, pady=24)

        try:
            if Image is None or ImageTk is None:
                raise RuntimeError("Pillow is not installed")
            img = Image.open(src_PATH + "logo/app_icon_full.png")
            img.thumbnail((int(320 * scale), int(150 * scale)), Image.Resampling.LANCZOS)
            self.about_logo_img = ImageTk.PhotoImage(img)
            tk.Label(container, image=self.about_logo_img, bg=self.colors["bg"]).pack(pady=(4, 14))
        except Exception as e:
            print("About logo load error:", e)

        tk.Label(
            container,
            text=APP_NAME,
            fg=self.colors["fg"],
            bg=self.colors["bg"],
            font=("Segoe UI", 18, "bold"),
        ).pack()

        tk.Label(
            container,
            text=f"Version {version} (Build {version_number})",
            fg=self.colors["muted"],
            bg=self.colors["bg"],
            font=("Segoe UI", 10),
        ).pack(pady=(4, 0))

        tk.Label(
            container,
            text=COPYRIGHT_TEXT,
            fg=self.colors["muted"],
            bg=self.colors["bg"],
            font=("Segoe UI", 9),
            wraplength=int(500 * scale),
            justify="center",
        ).pack(pady=(12, 18))

        ttk.Button(container, text="OK", command=about.destroy).pack(pady=(4, 0))
        about.bind("<Escape>", lambda _event: about.destroy())
        about.wait_window()

    def build_ui(self):
        self.setup_menu()

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        # Show the SSDL logo in the upper-left corner.
        # The image is resized with Pillow for better quality than PhotoImage.subsample().
        try:
            if Image is None or ImageTk is None:
                raise RuntimeError("Pillow is not installed")
            logo_path = src_PATH + "logo/ssdl_icon.png"
            logo_img = Image.open(logo_path)
            logo_img.thumbnail((125, 40), Image.Resampling.LANCZOS)
            self.logo_img = ImageTk.PhotoImage(logo_img)
            ttk.Label(top, image=self.logo_img).pack(side="left", padx=(0, 10))
        except Exception as e:
            print("Logo load error:", e)

        ttk.Label(top, text=APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(top, text=f"  ver {version}", style="Muted.TLabel").pack(side="left")
        ttk.Button(top, text="New", command=self.new_sequence).pack(side="right", padx=3)
        ttk.Button(top, text="Open", command=self.open_sequence).pack(side="right", padx=3)
        ttk.Button(top, text="Save", command=self.save_sequence).pack(side="right", padx=3)
        ttk.Button(top, text="Save As", command=self.save_sequence_as).pack(side="right", padx=3)

        paned = ttk.Panedwindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=4)

        left = ttk.Frame(paned, padding=6)
        right = ttk.Frame(paned, padding=6)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        def set_initial_sash():
            self.update_idletasks()
            paned.update_idletasks()
        
            total_width = paned.winfo_width()
        
            if total_width < 300:
                self.after(100, set_initial_sash)
                return

            paned.sashpos(0, int(total_width * 0.6))

        self.after(200, set_initial_sash)
        self.after(500, set_initial_sash)
        self.after(1000, set_initial_sash)


        toolbar = ttk.Frame(left)
        toolbar.pack(fill="x", pady=(0, 4))
        for text, cmd in [("+ Add", self.add_block), ("Edit", self.edit_block), ("Delete", self.delete_block), ("↑", self.move_up), ("↓", self.move_down)]:
            ttk.Button(toolbar, text=text, command=cmd).pack(side="left", padx=2)
        # ttk.Button(toolbar, text="Export raw text", command=self.refresh_text_from_blocks).pack(side="right", padx=2)

        columns = ("no", "raw_index", "status", "time", "command")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        self.tree.configure(displaycolumns=("no", "status", "time", "command"))
        self.tree.heading("no", text="#")
        self.tree.heading("status", text="Status")
        self.tree.heading("time", text="Execution time")
        self.tree.heading("command", text="Sequence")
        self.tree.column("no", width=30, anchor="e")
        self.tree.column("raw_index", width=0, minwidth=0, stretch=False)
        self.tree.column("status", width=60, anchor="center")
        self.tree.column("time", width=120, anchor="center")
        self.tree.column("command", width=400)
        self.tree.tag_configure("odd", background="#1b1b1b", foreground=self.colors["fg"])
        self.tree.tag_configure("even", background="#202020", foreground=self.colors["fg"])
        self.tree.tag_configure("running", background="#1f4e79", foreground="#ffffff")
        self.tree.tag_configure("done", background="#1b3a2a", foreground=self.colors["success"])
        self.tree.tag_configure("queued", background="#202020", foreground=self.colors["muted"])
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda e: self.edit_block())

        text_frame = ttk.LabelFrame(left, text="Raw sequence text")
        text_frame.pack(fill="both", expand=True, pady=(6, 0))
        self.raw_text = tk.Text(
            text_frame,
            height=8,
            wrap="none",
            bg=self.colors["field"],
            fg=self.colors["fg"],
            insertbackground=self.colors["fg"],
            selectbackground=self.colors["select"],
            selectforeground=self.colors["select_fg"],
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["accent"],
            font=("Courier", 12),
        )
        self.raw_text.pack(fill="both", expand=True)
        ttk.Button(text_frame, text="Import raw text to blocks", command=self.refresh_blocks_from_text).pack(anchor="e", padx=4, pady=4)

        status_frame = ttk.LabelFrame(right, text="Execution monitor")
        status_frame.pack(fill="x")
        self.file_label = ttk.Label(status_frame, text="File: untitled")
        self.file_label.pack(anchor="w", padx=6, pady=2)
        self.current_label = ttk.Label(status_frame, text="Running: -")
        self.current_label.pack(anchor="w", padx=6, pady=2)
        self.next_label = ttk.Label(status_frame, text="Next: -")
        self.next_label.pack(anchor="w", padx=6, pady=2)

        runbar = ttk.Frame(right)
        runbar.pack(fill="x", pady=6)
        self.run_btn = ttk.Button(runbar, text="Run sequence", command=self.run_sequence)
        self.run_btn.pack(side="left", padx=3)
        self.stop_btn = ttk.Button(runbar, text="Stop runner", command=self.stop_sequence, state="disabled")
        self.stop_btn.pack(side="left", padx=3)
        ttk.Button(runbar, text="Clear output", command=lambda: self.output.delete("1.0", "end")).pack(side="right", padx=3)

        out_frame = ttk.LabelFrame(right, text="Output")
        out_frame.pack(fill="both", expand=True)
        self.output = tk.Text(
            out_frame,
            wrap="word",
            bg="#0d1117",
            fg=self.colors["fg"],
            insertbackground=self.colors["fg"],
            selectbackground=self.colors["select"],
            selectforeground=self.colors["select_fg"],
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=self.colors["border"],
            highlightcolor=self.colors["accent"],
            font=("Cascadia Mono", 14),
        )
        self.output.pack(fill="both", expand=True)
        self.output.tag_config("start", foreground=self.colors["success"])
        self.output.tag_config("done", foreground=self.colors["success"])
        self.output.tag_config("prompt", foreground=self.colors["prompt"])
        self.output.tag_config("warning", foreground=self.colors["warning"])
        self.output.tag_config("error", foreground=self.colors["error"])
        self.output.tag_config("debug", foreground=self.colors["debug"])
        self.output.tag_config("info", foreground=self.colors["fg"])

        self.new_sequence()

    def set_running_ui(self, running: bool):
        self.run_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def add_log(self, tag, msg):
        self.output.insert("end", msg + "\n", tag)
        self.output.see("end")

    def log(self, tag, msg):
        self.q.put(("log", tag, msg))

    def ask(self, message, sound="notification", title="PWI4 Sequencer", parent=None, mode="okcancel"):
        """Show a standard Tk messagebox and return True/False.

        mode="ok"       : OK button only. Always returns True after OK/close.
                           If sound="alert", messagebox.showerror is used.
                           Otherwise, messagebox.showinfo is used.
        mode="okcancel" : OK and Cancel buttons. Returns True for OK, False for Cancel/close.
        mode="yesno"    : Yes and No buttons. Returns True for Yes, False for No/close.

        Sound playback is centralized here, so callers should not call
        play_alert_sound(), play_notification_sound(), etc. separately.
        """
        if sound == "alert":
            play_alert_sound()
        elif sound == "complete":
            play_complete_sound()
        elif sound == "end":
            play_end_sound()
        elif sound is False:
            pass
        else:
            play_notification_sound()

        mode = str(mode).lower()
        if mode not in {"ok", "okcancel", "yesno"}:
            mode = "okcancel"

        parent = parent or self

        if mode == "ok":
            if sound == "alert":
                messagebox.showerror(title, message, parent=parent, icon="question")
            else:
                messagebox.showinfo(title, message, parent=parent, icon="question")
            return True

        if mode == "yesno":
            return messagebox.askyesno(title, message, parent=parent, icon="question")

        return messagebox.askokcancel(title, message, parent=parent, icon="question")

    def ask_from_runner(self, message, sound="notification"):
        result_q = queue.Queue()
        self.q.put(("ask", message, sound, result_q))
        return result_q.get()

    def select_file_from_runner(self, **kwargs):
        result_q = queue.Queue()
        self.q.put(("select_file", kwargs, result_q))
        return result_q.get()

    def state_callback_from_runner(self, current, lines):
        self.q.put(("state", current, lines))

    def process_queue(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item[0] == "log":
                    _, tag, msg = item
                    self.add_log(tag, msg)
                elif item[0] == "ask":
                    _, msg, sound, result_q = item
                    result_q.put(self.ask(msg, sound=sound, parent=self))
                elif item[0] == "select_file":
                    _, kwargs, result_q = item
                    result_q.put(filedialog.askopenfilename(**kwargs))
                elif item[0] == "state":
                    _, current, lines = item
                    self.update_execution_state(current, lines)
                elif item[0] == "finished":
                    self.set_running_ui(False)
                elif item[0] == "update_check_result":
                    _, ok, latest_number, detail_text, error = item
                    self.handle_update_check_result(ok, latest_number, detail_text, error)
                elif item[0] == "update_prepare_result":
                    _, ok, result, error = item
                    self.handle_update_prepare_result(ok, result, error)
        except queue.Empty:
            pass
        self.after(100, self.process_queue)

    def update_execution_state(self, current, lines):
        self.current_index = current

        # The block editor table also serves as the execution monitor.
        # Comment/blank rows are intentionally NOT shown in this table.
        for iid in self.tree.get_children():
            raw_i = int(self.tree.set(iid, "raw_index"))
            line = self.tree.set(iid, "command")
            if current is None:
                self.tree.set(iid, "status", "")
                self.tree.set(iid, "time", sequence_schedule_label(line))
                self.tree.item(iid, tags=("even" if int(self.tree.set(iid, "no")) % 2 == 0 else "odd",))
            elif raw_i < current:
                self.tree.set(iid, "status", "Done")
                self.tree.set(iid, "time", sequence_schedule_label(line))
                self.tree.item(iid, tags=("done",))
            elif raw_i == current:
                self.tree.set(iid, "status", "Running")
                self.tree.set(iid, "time", sequence_schedule_label(line))
                self.tree.item(iid, tags=("running",))
                self.tree.selection_set(iid)
                self.tree.see(iid)
            else:
                self.tree.set(iid, "status", "Queued")
                self.tree.set(iid, "time", sequence_schedule_label(line))
                self.tree.item(iid, tags=("queued",))
        if current is None:
            self.current_label.configure(text="Running: -")
            self.next_label.configure(text="Next: -")
        else:
            self.current_label.configure(text=f"Running: [{sequence_schedule_label(lines[current])}] {normalize_line(lines[current])}")
            nxt = "-"
            for i in executable_indices(lines):
                if i > current:
                    nxt = f"[{sequence_schedule_label(lines[i])}] {normalize_line(lines[i])}"
                    break
            self.next_label.configure(text=f"Next: {nxt}")

    def get_lines_from_tree(self):
        return [self.tree.set(iid, "command") for iid in self.tree.get_children()]

    def rebuild_tree_from_lines(self):
        self.tree.delete(*self.tree.get_children())
        exec_no = 1
        for raw_i, line in enumerate(self.lines):
            if not is_executable_sequence(line):
                continue
            tag = "even" if exec_no % 2 == 0 else "odd"
            self.tree.insert("", "end", values=(exec_no, raw_i, "", sequence_schedule_label(line), normalize_line(line)), tags=(tag,))
            exec_no += 1

    def set_lines(self, lines):
        self.lines = [ln.rstrip("\n") for ln in lines]
        self.rebuild_tree_from_lines()
        self.raw_text.delete("1.0", "end")
        self.raw_text.insert("1.0", "\n".join(self.lines))

    def refresh_text_from_blocks(self):
        self.lines = self.get_lines_from_tree()
        for iid in self.tree.get_children():
            line = self.tree.set(iid, "command")
            self.tree.set(iid, "time", sequence_schedule_label(line))
        self.raw_text.delete("1.0", "end")
        self.raw_text.insert("1.0", "\n".join(self.lines))
        self.rebuild_tree_from_lines()

    def refresh_blocks_from_text(self):
        lines = self.raw_text.get("1.0", "end").splitlines()
        self.set_lines(lines)

    def renumber(self):
        for i, iid in enumerate(self.tree.get_children(), start=1):
            self.tree.set(iid, "no", i)
            self.tree.set(iid, "raw_index", i - 1)

    def add_block(self):
        dlg = AddBlockDialog(self)
        if dlg.result_line and is_executable_sequence(dlg.result_line):
            time_label = sequence_schedule_label(dlg.result_line)
            n = len(self.tree.get_children()) + 1
            self.tree.insert("", "end", values=(n, n - 1, "", time_label, normalize_line(dlg.result_line)))
            self.refresh_text_from_blocks()

    def edit_block(self):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        old = self.tree.set(iid, "command")
        dlg = AddBlockDialog(self, initial_text=old)
        if dlg.result_line:
            if is_executable_sequence(dlg.result_line):
                self.tree.set(iid, "command", normalize_line(dlg.result_line))
                self.tree.set(iid, "time", sequence_schedule_label(dlg.result_line))
            else:
                self.tree.delete(iid)
                self.renumber()
            self.refresh_text_from_blocks()
    def delete_block(self):
        sel = self.tree.selection()
        if not sel:
            return
        self.tree.delete(sel[0])
        self.renumber()
        self.refresh_text_from_blocks()

    def move_up(self):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        idx = self.tree.index(iid)
        if idx > 0:
            self.tree.move(iid, "", idx - 1)
            self.renumber()
            self.refresh_text_from_blocks()

    def move_down(self):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        idx = self.tree.index(iid)
        if idx < len(self.tree.get_children()) - 1:
            self.tree.move(iid, "", idx + 1)
            self.renumber()
            self.refresh_text_from_blocks()

    def new_sequence(self):
        self.filename = None
        self.set_lines([
            "CONNECTPWI4",
            "STARTPWI4"
        ])
        self.file_label.configure(text="File: untitled")

    def open_sequence(self):
        fn = filedialog.askopenfilename(
            title="Open sequence file",
            initialdir=appPATH + "example" if path.isdir(appPATH + "example") else appPATH,
            filetypes=[("Sequence files", "*.pws *.PWS *.txt *.TXT"), ("All files", "*.*")],
        )
        if not fn:
            return
        try:
            with open(fn, encoding="utf-8") as f:
                self.set_lines(f.read().splitlines())
            self.filename = fn
            self.file_label.configure(text=f"File: {fn}")
        except Exception as exc:
            play_alert_sound()
            messagebox.showerror("Open error", str(exc))

    def save_sequence(self):
        if not self.filename:
            return self.save_sequence_as()
        self.lines = self.raw_text.get("1.0", "end").splitlines()
        with open(self.filename, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(self.lines) + "\n")
        self.file_label.configure(text=f"File: {self.filename}")

    def save_sequence_as(self):
        fn = filedialog.asksaveasfilename(
            title="Save sequence file",
            initialdir=appPATH,
            defaultextension=".pws",
            filetypes=[("PWI Sequence", "*.pws"), ("Text", "*.txt"), ("All files", "*.*")],
        )
        if not fn:
            return
        self.filename = fn
        self.save_sequence()

    def run_sequence(self):
        if self.runner_thread and self.runner_thread.is_alive():
            return
        self.refresh_blocks_from_text()
        lines = list(self.lines)
        filename = self.filename or "untitled"
        self.runner = SequenceRunner(self.log, self.ask_from_runner, self.select_file_from_runner, self.state_callback_from_runner)
        self.set_running_ui(True)
        def target():
            try:
                self.runner.run_sequence(lines, filename)
            except KeyboardInterrupt:
                play_alert_sound()
                self.log("error", " X Sequence terminated")
            except Exception:
                play_alert_sound()
                self.log("error", " X ERROR : Runner crashed")
                self.log("debug", traceback.format_exc())
            finally:
                self.q.put(("finished",))
        self.runner_thread = threading.Thread(target=target, daemon=True)
        self.runner_thread.start()

    def stop_sequence(self):
        if self.runner:
            self.runner.request_stop()
            self.add_log("warning", " ! Stop requested. Waiting for current blocking PWI4 operation/check loop to return...")


if __name__ == "__main__":
    root = SequencerGUI()
    root.withdraw()

    splash = SplashScreen(root, duration=3000)

    def show_main():
        splash.destroy()
        root.deiconify()

    root.after(3000, show_main)
    root.mainloop()
