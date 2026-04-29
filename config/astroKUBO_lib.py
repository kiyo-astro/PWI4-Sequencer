import requests
from datetime import datetime, timedelta

class space_track:
    def get_recent_TLE(norad_id,user_id,password):
        # Start Session
        session = requests.Session()

        # Log in
        login_url = 'https://www.space-track.org/ajaxauth/login'
        login_payload = {
            'identity': user_id,
            'password': password
        }

        response = session.post(login_url, data=login_payload)
        if response.status_code != 200:
            tle_result = "FAILED TO LOG IN"
        
        else:
            # Get TLE data
            query_url = (
                "https://www.space-track.org/basicspacedata/query/class/gp/"
                "NORAD_CAT_ID/{0}/"
                "orderby/TLE_LINE1%20ASC/format/3le".format(norad_id)
            )

            response = session.get(query_url, stream=True)

            if response.status_code == 200:
                tle_result = response.text
            else:
                tle_result = "FAILED TO GET TLE"

        return response.status_code,tle_result

class celes_trak:
    def get_recent_TLE(norad_id):
        # Start Session
        session = requests.Session()

        # Get TLE data
        query_url = (
            "https://celestrak.org/NORAD/elements/gp.php?CATNR={0}".format(norad_id)
        )

        response = session.get(query_url, stream=True)

        if response.status_code == 200:
            tle_result = response.text
        else:
            tle_result = "FAILED TO GET TLE"

        return response.status_code,tle_result
class tle_reader:
    def parse_tle_epoch(tle_line1):
        try:
            year = int(tle_line1[18:20])
            year += 2000 if year < 57 else 1900
            day_of_year = float(tle_line1[20:32])
            date = datetime(year, 1, 1) + timedelta(days=day_of_year - 1)
            return date.strftime('%Y-%m-%dT%H:%M:%S UTC')
        except Exception as e:
            return "Error"