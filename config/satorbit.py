#--------------------------------------------------------------------------------------------------#
# satorbit.py                                                                                      #
# Developed by Kiyoaki Okudaira * University of Washington / Kyushu University / IAU CPS SatHub    #
#--------------------------------------------------------------------------------------------------#
# Description                                                                                      #
#--------------------------------------------------------------------------------------------------#
# Calculate satellite orbit from TLE with SPICE toolkit                                            #
#--------------------------------------------------------------------------------------------------#
# History                                                                                          #
#--------------------------------------------------------------------------------------------------#
# coding 2025.12.07: 1st coding                                                                    #
#--------------------------------------------------------------------------------------------------#

#--------------------------------------------------------------------------------------------------#
# Libraries                                                                                        #
#--------------------------------------------------------------------------------------------------#
import spiceypy as spice
import numpy as np
import erfa
from pathlib import Path
import math

#--------------------------------------------------------------------------------------------------#
# Main                                                                                             #
#--------------------------------------------------------------------------------------------------#
_, EARTH_RADII = spice.bodvcd(399, "RADII", 3)
EARTH_FLATTENING = (EARTH_RADII[0] - EARTH_RADII[2]) / EARTH_RADII[0]
SUN_RADIUS_KM = 696000.0

def get_planetconst(
        planet_id: int | str,
        items: list
        ):
    """
    Get planetary constants from SPICE toolkit

    Parameters
    ----------
    planet_id: `int`
        NAIF integer ID code for a body of interest
    items: `list` or `str`
        items to be returned

    Returns
    -------
    constants: `numpy.ndarray`
        List of plantetary constants requested

    Notes
    -----
        (c) 2025 Kiyoaki Okudaira - Kyushu University Hanada Lab (SSDL) / IAU CPS SatHub
    """
    if type(items) is str:
        items = [items]
    constants = np.zeros(len(items), dtype=float)

    for i, name in enumerate(items):
        dim, values = spice.bodvcd(planet_id, name, 1)
        if dim < 1:
            raise RuntimeError(f"Could not retrieve {name} for Earth from kernels. Please refer to https://naif.jpl.nasa.gov/pub/naif/misc/toolkit_docs_N0067/C/cspice/bodvcd_c.html")
        constants[i] = values[0]
    
    return constants

def read_TLEfile(
        tle_path: str
        ):
    """
    Read TLE file and get satellite name

    Parameters
    ----------
    tle_path: `str`
        PATH of TLE file

    Returns
    -------
    satname: `str` or None
        Satellite name. If file is NOT 3LE, return None
    line1: `str`
        TLE line 1
    line2: `str`
        TLE line 2

    Notes
    -----
        (c) 2025 Kiyoaki Okudaira - Kyushu University Hanada Lab (SSDL) / IAU CPS SatHub
    """
    p = Path(tle_path)

    if not p.is_file():
        raise FileNotFoundError(f"TLE file not found: {tle_path}")

    with p.open("r", encoding="utf-8") as f:
        first = ""
        for line in f:
            first = line.strip()
            if first:
                break

        if not first:
            raise ValueError("TLE file is empty or only has blank lines.")

        if first[0] == "1":
            satname = None
            line1 = first
        else:
            satname = first
            line1 = f.readline().strip()

        line2 = f.readline().strip()

    if not line1 or not line2:
        raise ValueError("TLE file does not contain two TLE lines.")

    return satname, line1, line2

def parse_TLE2element(
        line1: str,
        line2: str,
        frstyr: int = 1957
        ):
    """
    Parse lines of TLE to elements suitable for SPICE software 

    Parameters
    ----------
    line1: `str`
        TLE line 1
    line2: `str`
        TLE line 2
    frstyr: `int`, optional
        Year of earliest representable two-line elements. Default is 1957

    Returns
    -------
    epoch: `float`
        Epoch of the elements in seconds past J2000
    elems: `numpy.ndarray`
        Elements converted to SPICE units

    Notes
    -----
        (c) 2025 Kiyoaki Okudaira - Kyushu University Hanada Lab (SSDL) / IAU CPS SatHub
    """
    lines = [line1, line2]
    epoch, elems = spice.getelm(frstyr, lines)
    return epoch, elems

def geo2itrf(
        gd_lon: float,
        gd_lat: float,
        gd_height: float
        ):
    """
    Convert geodetic coordinates to rectangular coordinates 

    Parameters
    ----------
    gd_lon: `float`
        Geodetic longitude [radian]
    gd_lat: `float`
        Geodetic latitude [radian]
    gd_height: `float`
        Geodetic height [km]

    Returns
    -------
    site_itrf: `numpy.ndarray`
        Rectangular coordinates of point (ITRF) [km]

    Notes
    -----
        (c) 2025 Kiyoaki Okudaira - Kyushu University Hanada Lab (SSDL) / IAU CPS SatHub
    """
    site_itrf = spice.georec(gd_lon,gd_lat,gd_height,EARTH_RADII[0],EARTH_FLATTENING)
    return site_itrf

def teme2J2000(
        state_teme: np.ndarray,
        et: float
        ):
    """
    Convert TEME coordinates to J2000 coordinates 

    Parameters
    ----------
    state_teme: `numpy.ndarray`
        Satellite state (position and velosity) in TEME coordinates [km]
    et: `float`
        Epoch

    Returns
    -------
    state_j2000: `numpy.ndarray`
        Satellite state (position and velosity) in J2000 coordinates [km]

    Notes
    -----
        (c) 2025 Kiyoaki Okudaira - Kyushu University Hanada Lab (SSDL) / IAU CPS SatHub
    """
    # EPOCH to JD
    jdtdb = spice.unitim(et, "ET", "JDTDB")

    # ERFA equation of equinoxes
    ee = erfa.eqeq94(jdtdb, 0.0)

    # TEME => ToD
    rot = spice.rotate(-ee, 3)
    pos_tod = spice.mxv(rot, state_teme[0:3])
    vel_tod = spice.mxv(rot, state_teme[3:6])
    state_tod = np.hstack([pos_tod, vel_tod])

    # TOD => J2000
    xform = spice.sxform("TOD", "J2000", et)
    state_j2000 = spice.mxvg(xform, state_tod)

    return state_j2000

def itrf2J2000(
        site_itrf: np.ndarray,
        et: float
        ):
    """
    Convert ITRF coordinates to J2000 coordinates 

    Parameters
    ----------
    site_itrf: `numpy.ndarray`
        Rectangular coordinates of point (ITRF) [km]
    et: `float`
        Epoch

    Returns
    -------
    site_j2000: `numpy.ndarray`
        J2000 coordinates of point [km]
    
    Notes
    -----
        (c) 2025 Kiyoaki Okudaira - Kyushu University Hanada Lab (SSDL) / IAU CPS SatHub
    """
    xform = spice.sxform("ITRF93", "J2000", et)
    mat3 = np.array([row[0:3] for row in xform[0:3]], dtype=float)
    site_j2000 = spice.mxv(mat3, site_itrf)
    return site_j2000

def J20002radec(
        pos_j2000: np.ndarray,
        site_j2000: np.ndarray
        ):
    """
    Convert J2000 coordinates to RADEC and range 

    Parameters
    ----------
    pos_j2000: `numpy.ndarray`
        J2000 coordinates of satellite position [km]
    site_j2000: `float`
        J2000 coordinates of point [km]

    Returns
    -------
    range_km: `float`
        Range [km]
    ra: `float`
        Right ascension [radian]
    dec: `float`
        Declination [radian]
    
    Notes
    -----
        (c) 2025 Kiyoaki Okudaira - Kyushu University Hanada Lab (SSDL) / IAU CPS SatHub
    """
    rel_vec = pos_j2000 - site_j2000
    range_km, ra, dec = spice.recrad(rel_vec)
    return range_km, ra, dec

def J20002itrf(
        state_j2000: np.ndarray,
        et: float
        ):
    """
    Convert J2000 coordinates to ITRF coordinates 

    Parameters
    ----------
    state_j2000: `numpy.ndarray`
        Satellite state (position and velosity) in J2000 coordinates [km]
    et: `float`
        Epoch

    Returns
    -------
    state_itrf: `numpy.ndarray`
        Satellite state (position and velosity) in ITRF coordinates [km]
    
    Notes
    -----
        (c) 2025 Kiyoaki Okudaira - Kyushu University Hanada Lab (SSDL) / IAU CPS SatHub
    """
    xform = spice.sxform("J2000", "ITRF93", et)
    state_itrf = spice.mxvg(xform, state_j2000)
    return state_itrf

def itrf2azel(
        pos_itrf: np.ndarray,
        site_itrf: np.ndarray,
        gd_lon: float,
        gd_lat: float
        ):
    """
    Convert ITRF coordinates to Azimuth and Elevation 

    Parameters
    ----------
    sat_itrf: `numpy.ndarray`
        ITRF coordinates of satellite position [km]
    site_itrf: `float`
        ITRF coordinates of point [km]
    gd_lon: `float`
        Geodetic longitude [radian]
    gd_lat: `float`
        Geodetic latitude [radian]

    Returns
    -------
    range_km: `float`
        Range [km]
    az: `float`
        Azimuth (0 <= az < 2*pi) [radian]
    el: `float`
        Elevation [radian]
    
    Notes
    -----
        (c) 2025 Kiyoaki Okudaira - Kyushu University Hanada Lab (SSDL) / IAU CPS SatHub
    """
    # Relative position
    rel_itrf = spice.vsub(pos_itrf,site_itrf)

    # ITRF => SEZ（South-East-Zenith)
    sez = spice.rotvec(rel_itrf, gd_lon, 3)
    sez = spice.rotvec(sez, np.pi/2.0 - gd_lat, 2)

    # SEZ => range, Az, El
    range_km, az, el = spice.recazl(sez, False, True,)

    # Modify Az to range 0 <= az < 2*pi
    az += np.pi
    if az > 2.0 * np.pi:
        az -= 2.0 * np.pi
    return range_km, az, el

def check_umbra(
        pos_j2000: np.ndarray,
        et: float
        ):
    """
    Check if satellite is in umbra 

    Parameters
    ----------
    pos_j2000: `numpy.ndarray`
        J2000 coordinates of satellite position [km]
    et: `float`
        Epoch

    Returns
    -------
    in_umbra: `bool`
        Range [km]
    
    Notes
    -----
        (c) 2025 Kiyoaki Okudaira - Kyushu University Hanada Lab (SSDL) / IAU CPS SatHub
    """
    # Position of the sun in J2000 from the Earth
    sun_vec, lt = spice.spkgps(10, et, "J2000", 399)
    sun_vec = np.asarray(sun_vec, dtype=float)

    # Position of the sun in J2000 from satellite
    r_sun_sat = sun_vec - pos_j2000
    sun_hat, d_sun_sat = spice.unorm(r_sun_sat)

    # Position of the Earth in J2000 from satellite
    r_earth_sat = -pos_j2000
    earth_hat, d_earth_sat = spice.unorm(r_earth_sat)

    # Distance
    if d_sun_sat <= SUN_RADIUS_KM:
        a = math.pi / 2.0
    else:
        a = math.asin(SUN_RADIUS_KM / d_sun_sat)

    if d_earth_sat <= EARTH_RADII[0]:
        b = math.pi / 2.0
    else:
        b = math.asin(EARTH_RADII[0] / d_earth_sat)

    # Phase angle
    c = spice.vsep(sun_hat, earth_hat)  # [rad]

    # Check umbra
    if b <= a:
        in_umbra = False

    in_umbra = (c <= (b - a))

    return in_umbra

def phase_angle(
        pos_j2000: np.ndarray,
        site_j2000: np.ndarray,
        et: float
        ):
    """
    Calculate solar phase angle of satellite 

    Parameters
    ----------
    pos_j2000: `numpy.ndarray`
        J2000 coordinates of satellite position [km]
    site_j2000: `float`
        J2000 coordinates of point [km]

    Returns
    -------
    phase: `float`
        Solar phase angle [radian]
    
    Notes
    -----
        (c) 2025 Kiyoaki Okudaira - Kyushu University Hanada Lab (SSDL) / IAU CPS SatHub
    """
    # Position of the sun in J2000 from the Earth
    sun_vec, lt = spice.spkgps(10, et, "J2000", 399)
    sun_vec = np.asarray(sun_vec, dtype=float)

    # Position of the sun in J2000 from satellite
    r_sun_sat = sun_vec - pos_j2000

    # Position of observer in J2000 from satellite
    r_obs_sat = site_j2000 - pos_j2000

    # Solar phase angle
    phase = spice.vsep(r_sun_sat, r_obs_sat)

    return phase

def apparent_v(
        state_j2000: np.ndarray,
        site_itrf: np.ndarray,
        et
        ):
    """
    Calculate solar phase angle of satellite 

    Parameters
    ----------
    state_j2000: `numpy.ndarray`
        Satellite state (position and velosity) in J2000 coordinates [km]
    site_itrf: `float`
        ITRF coordinates of point [km]
    et: `float`
        Epoch

    Returns
    -------
    apparent_v_km_s: `float`
        Apparent velocity of satellite [km]
    
    Notes
    -----
        (c) 2025 Kiyoaki Okudaira - Kyushu University Hanada Lab (SSDL) / IAU CPS SatHub
    """
    site6_itrf = np.zeros(6, dtype=float)
    site6_itrf[0:3] = site_itrf

    xform = spice.sxform("ITRF93", "J2000", et)
    site6_j2000 = spice.mxvg(xform, site6_itrf)

    # site6_j2000 = np.zeros(6, dtype=float)
    # site6_j2000[0:3] = site_j2000
    
    rel_j2000 = state_j2000 - site6_j2000
    x, y, z, vx, vy, vz = rel_j2000

    range_km, _, dec_rad = spice.recrad(rel_j2000[0:3])

    x2py2 = x * x + y * y
    drange = (x * vx + y * vy + z * vz) / range_km
    drac = (x * vy - y * vx) * math.cos(dec_rad) / x2py2
    ddec = (vz - drange * math.sin(dec_rad)) / math.sqrt(x2py2)

    apparent_v_km_s = math.sqrt(drac * drac + ddec * ddec) * range_km

    return apparent_v_km_s

#--------------------------------------------------------------------------------------------------#
# Test                                                                                             #
#--------------------------------------------------------------------------------------------------#