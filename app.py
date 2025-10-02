import json
import requests
import urllib3
import sys
# import re
import os
import time
# import tzlocal
import socket
from datetime import datetime
import logging
from apscheduler.schedulers.background import BackgroundScheduler

# from fastapi import FastAPI, HTTPException, Depends, Request, Response, status
from fastapi import FastAPI, HTTPException, Depends, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

os.environ['TZ'] = 'Europe/Stockholm'
if hasattr(time, 'tzset'):
    time.tzset()

apiuser = os.environ.get('APIUSER')
apipass = os.environ.get('APIPASS')
DISCORD_ID = os.environ.get('DISCORD_ID')
DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN')

# Data sources
ISN_URL = 'https://services.swpc.noaa.gov/json/f107_cm_flux.json'
KP_URL = 'https://services.swpc.noaa.gov/json/planetary_k_index_1m.json'

# Splunk test url and headers
splunkurl = 'https://splunk.home:8088/services/collector/event?sourcetype=isn_daily'
splunkheaders = {
    'Authorization': 'Splunk 0dffc34c-268f-4b38-88a2-9f3e67498f2c'}

# Splunk index
index = 'isn'

# Elasticearch params & headers
esurl = 'http://elasticsearch.home:9200/solar/_doc/'
esheaders = {'Content-Type': 'application/json'}


app = FastAPI()
security = HTTPBasic()


def getAuth(credentials: HTTPBasicCredentials = Depends(security)):

    # correct_username = secrets.compare_digest(credentials.username.lower(), apiuser.lower())
    # correct_password = secrets.compare_digest(credentials.password, apipass)
    # if not (correct_username and correct_password):

    if not (credentials.username.lower() == apiuser and credentials.password == apipass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect user or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# Blynk threaded setup
# Blynk auth token
BLYNK_API_URL = os.environ.get("BLYNK_API_URL")
BLYNK_TOKEN = os.environ.get("BLYNK_TOKEN")

# Set up logging
logging.basicConfig(
    format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO)

# Disable https warning
urllib3.disable_warnings()

# Extract version from package.json and print to console
try:
    with open('package.json', 'r') as f:
        package_data = json.load(f)
        version = package_data.get('version', 'Unknown')
        print(f"Version: {version}")
except FileNotFoundError:
    logging.info("package.json not found.")
except json.JSONDecodeError:
    logging.info("Failed to decode package.json.")


def dailyIsnIngest():
    logging.info('---  ingest scheduler start ---')
    data = get_data(ISN_URL)
    isn, flux_10cm, Kp, epoch, date = extract_isn(data)

    # logging.info('---  Sending to Splunk ---')
    # resp = hec_send(isn, flux_10cm, Kp, epoch)
    # logging.info('Splunk response: %s', resp)

    logging.info('---  Sending to Elastic ---')
    resp = es_send(isn, flux_10cm, Kp, date)
    logging.info('Elasticsearch response: %s', resp)

    logging.info('---  ingest scheduler end  ---')

    dailyData = dict(isn=isn, flux_10cm=flux_10cm, Kp=Kp, date=date)
    return dailyData


def dailyIsnDiscord():
    logging.info('--- Discord scheduler start ---')
    ISN_DATA = get_data(ISN_URL)
    KP_DATA = get_data(KP_URL)
    isn, flux_10cm, epoch, date = extract_isn(ISN_DATA)
    kp = extract_kp(KP_DATA)

    resp = discord_post(isn, flux_10cm, kp)
    logging.info('Discord: %s', resp)
    logging.info('---  Discord scheduler end  ---')


def postBlynk():
    logging.info('--- Blynk scheduler start ---')
    ISN_DATA = get_data(ISN_URL)
    KP_DATA = get_data(KP_URL)
    isn, flux_10cm, epoch, date = extract_isn(ISN_DATA)
    kp = extract_kp(KP_DATA)

    # blynk.virtual_write(31, isn)
    # blynk.virtual_write(32, flux_10cm)
    # blynk.virtual_write(33, Kp)

    def pinurl(pin, metric):
        pinUrl = BLYNK_API_URL + '/' + BLYNK_TOKEN + \
            '/update/' + pin + '?value=' + str(metric)  # Convert metric to string
        return pinUrl

    pinUrl = pinurl('V31', isn)
    requests.get(pinUrl, verify=False)

    pinUrl = pinurl('V32', flux_10cm)
    requests.get(pinUrl, verify=False)

    pinUrl = pinurl('V33', kp)
    requests.get(pinUrl, verify=False)

    logging.info('Posted to Blynk: ISN, Flux, Kp; %s %s %s',
                 isn, flux_10cm, kp)
    logging.info('---  Blynk scheduler end  ---')


def get_data(url):
    logging.info('Getting data...')
    try:
        r = requests.get(url)
        r.raise_for_status()
        data = r.json()
        logging.info('Data from %s loaded ok. %s', url, r)
        return data
    except requests.exceptions.HTTPError as err:
        logging.error('Data %s load failed. %s Error: %s', url, r, err)
    except Exception as e:
        logging.error('Data load, some other error: %s', e)


def extract_kp(data):
    try:
        logging.info('Extracting Kp-index data...')
        if not data:
            raise ValueError("No data found in the response.")

        # Sort data by time_tag to get the most recent entry
        data.sort(key=lambda x: x['time_tag'], reverse=True)
        latest_entry = data[0]

        kp = latest_entry.get('kp_index', None)
        if kp is None:
            raise ValueError("Kp value not found in the response.")
        # Convert kp to an integer
        try:
            kp = int(kp)
        except ValueError as e:
            logging.error('Failed to convert kp to integer: %s', e)
            raise
        time_tag = latest_entry['time_tag']
        # date_object = datetime.strptime(time_tag, '%Y-%m-%dT%H:%M:%S')
        # epoch = time.mktime(date_object.timetuple())
        # esdate_object = date_object.strftime('%Y-%m-%dT%H:%M:%S')

        logging.debug('Date: %s', time_tag)
        logging.debug('Kp Index: %s', kp)
    except json.JSONDecodeError as e:
        logging.error('JSON decode error: %s', e)
    except ValueError as e:
        logging.error('Value Error: %s', e)
    except Exception as e:
        logging.error('Extract data, other error: %s', e)
    else:
        # return kp, epoch, esdate_object
        return kp


def extract_isn(data):
    try:
        logging.info('Extracting ISN data...')
        if not data:
            raise ValueError("No data found in the response.")

        # Sort data by time_tag to get the most recent entry
        data.sort(key=lambda x: x['time_tag'], reverse=True)
        latest_entry = data[0]

        flux_10cm = latest_entry.get('flux', None)
        if flux_10cm is None:
            raise ValueError("Flux value not found in the response.")
        # Convert flux_10cm to an integer
        try:
            flux_10cm = int(flux_10cm)
        except ValueError as e:
            logging.error('Failed to convert flux_10cm to integer: %s', e)
            raise
        # Extract other necessary values (if needed)
        time_tag = latest_entry['time_tag']
        date_object = datetime.strptime(time_tag, '%Y-%m-%dT%H:%M:%S')
        epoch = time.mktime(date_object.timetuple())
        esdate_object = date_object.strftime('%Y-%m-%dT%H:%M:%S')

        # Assuming isn and Kp are not available in the new format
        # Calculate isn based on the formula
        logging.info('Calculating ISN from 10.7cm flux... (isn=int((1.14)*flux_10cm-73.21))')
        isn = int((1.14) * flux_10cm - 73.21)
        # Kp = '0'

        logging.debug('Date:: %s', time_tag)
        logging.debug('Daily ISN Count: %s', isn)
        logging.debug('Daily 10.7cm Flux: %s', flux_10cm)
        # logging.debug('Daily Kp Index: %s', Kp)
    except json.JSONDecodeError as e:
        logging.error('JSON decode error: %s', e)
    except ValueError as e:
        logging.error('Value Error: %s', e)
    except Exception as e:
        logging.error('Extract data, other error: %s', e)
    else:
        return isn, flux_10cm, epoch, esdate_object

# Build and post payload to Splunk HEC


def hec_send(isn, flux_10cm, Kp, date):
    logging.info('--- Posting to Splunk...')
    payload = {}
    payload['time'] = date
    payload['index'] = index
    payload['event'] = {}
    payload['event']['isn'] = isn
    payload['event']['flux_10cm'] = flux_10cm
    payload['event']['Kp'] = Kp

    # Post to splunk
    try:
        r = requests.post(splunkurl, data=json.dumps(payload),
                          headers=splunkheaders, verify=False)
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logging.error('--- Splunk post failed. Error: %s', e)
    except Exception as e:
        logging.error('Data load, some other error: %s', e)
    else:
        return r

# Build and post payload to Splunk HEC


def es_send(isn, flux_10cm, Kp, date):
    logging.info('--- Posting to Elasticsearch...')
    # Need to convert to number
    isn = float(isn)
    flux_10cm = float(flux_10cm)
    Kp = float(Kp)

    # date = str(date)
    payload = {}
    payload['@timestamp'] = date
    payload['isn'] = isn
    payload['flux_10cm'] = flux_10cm
    payload['Kp'] = Kp

    # Post to Elasticsearch
    try:
        r = requests.post(esurl, data=json.dumps(payload),
                          headers=esheaders, verify=False)
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logging.error('--- Elasticsearch post failed. Error: %s', e)
    except Exception as e:
        logging.error('Data load, some other error: %s', e)
    else:
        return r


def discord_post(isn, flux_10cm, Kp):
    logging.info('--- Posting to Discord...')
    # msg must be formatted as dict ['content'] = "message"
    msg = dict()
    msg['content'] = 'ISN: ' + isn + \
        ', 10cm Flux: ' + flux_10cm + ', Kp: ' + Kp
    url = f'https://discordapp.com/api/webhooks/{DISCORD_ID}/{DISCORD_TOKEN}'
    headers = {'content-type': 'application/json'}
    try:
        r = requests.post(url, json=msg, headers=headers, verify=False)
        r.raise_for_status()
    except requests.exceptions.HTTPError as err:
        logging.error(
            '--- Siscord post failed, %s load failed. %s Error: %s', url, r, err)
    except Exception as e:
        logging.error('Data load, some other error: %s', e)
    else:
        return r

# routes


@app.get("/test")
async def test(request: Request, status_code=200, username: str = Depends(getAuth)):  # <- uses auth decorator
    # response.status_code = 201
    client = request.client.host
    hostname = socket.gethostname()
    return dict(hostname=hostname, user=username, client=client)


@app.get("/")
@app.get("/api/v1/isn")
@app.get("/v1/isn")
async def home(request: Request):
    logging.info('Solar data response to client: %s',
                 request.client.host)
    ISN_DATA = get_data(ISN_URL)
    KP_DATA = get_data(KP_URL)
    isn, flux_10cm, epoch, date = extract_isn(ISN_DATA)
    kp = extract_kp(KP_DATA)
    daily = dict(isn=isn, flux_10cm=flux_10cm, Kp=kp, date=date)
    response = dict(solar=daily)
    # responseCode = 200
    # return make_response(jsonify(response), responseCode)
    return response


@app.get("/health")
async def health(request: Request):
    client = request.client.host
    logging.info('Health enpoint response to client %s', client)
    hostname = socket.gethostname()
    return dict(status="healthy", hostname=hostname)

# Set up the scheduler
sched = BackgroundScheduler(daemon=True)
# Schedule the ingestion every 6 hours
sched.add_job(func=dailyIsnIngest, trigger='interval', hours=24)
# Schedule posting to discord every 12 hours
sched.add_job(func=dailyIsnDiscord, trigger='interval', hours=24)
# Schedule posting to Blynk
sched.add_job(func=postBlynk, trigger='interval', minutes=60)
# start all schedulers
sched.start()
# Log all sched jobs
logging.info(sched.print_jobs(out=sys.stdout))
