import json
import requests
import urllib3
import sys
import re
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


app = FastAPI()
security = HTTPBasic()

# APM
# from elasticapm.contrib.flask import ElasticAPM

# app.config['ELASTIC_APM'] = {
#   # Set required service name. Allowed characters:
#   # a-z, A-Z, 0-9, -, _, and space
#   'SERVICE_NAME': 'nova2046',

#   # Use if APM Server requires a token
#   'SECRET_TOKEN': '',

#   # Set custom APM Server URL (default: http://localhost:8200)
#   'SERVER_URL': 'http://apm.home:8200',
# }
# apm = ElasticAPM(app)
# APM


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

# import blynklib
# import threading


# Blynk threaded setup
# Blynk auth token
BLYNK_API_URL = os.environ.get("BLYNK_API_URL")
BLYNK_TOKEN = os.environ.get("BLYNK_TOKEN")

# Init blynk
# blynk = blynklib.Blynk(BLYNK_TOKEN, server="192.168.1.100", port=8081)

# APP_CONNECT_PRINT_MSG = '[APP_CONNECT_EVENT]'
# APP_DISCONNECT_PRINT_MSG = '[APP_DISCONNECT_EVENT]'

# @blynk.handle_event('internal_acon')
# def app_connect_handler(*args):
#     print(APP_CONNECT_PRINT_MSG)


# @blynk.handle_event('internal_adis')
# def app_disconnect_handler(*args):
#     print(APP_DISCONNECT_PRINT_MSG)

# create blynk loop that will run as own thread
# def blynkLoop():
# 	global blynk
# 	print("Blynk thread Started")
# 	#blynk.set_user_task(my_user_task, 1000)
# 	blynk.run()

# Start blynk background thread
# t = threading.Thread(target = blynkLoop, daemon = True)
# t = threading.Thread(target = blynkLoop)
# t.start()
# Blynk threaded setup

# Set up logging
logging.basicConfig(
    format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO)

# Disable https warning
urllib3.disable_warnings()


def dailyIsnIngest():
    logging.info('---  ingest scheduler start ---')
    page = get_page(isn_url)
    isn, flux_10cm, Kp, epoch, date = extract_data(page)

    logging.info('---  Sending to Splunk ---')
    resp = hec_send(isn, flux_10cm, Kp, epoch)
    logging.info('Splunk response: %s', resp)

    logging.info('---  Sending to Elastic ---')
    resp = es_send(isn, flux_10cm, Kp, date)
    logging.info('Elasticsearch response: %s', resp)

    logging.info('---  ingest scheduler end  ---')

    dailyData = dict(isn=isn, flux_10cm=flux_10cm, Kp=Kp, date=date)
    return dailyData


def dailyIsnDiscord():
    logging.info('--- Discord scheduler start ---')
    page = get_page(isn_url)
    isn, flux_10cm, Kp, epoch, date = extract_data(page)

    resp = discord_post(isn, flux_10cm, Kp)
    logging.info('Discord: %s', resp)
    logging.info('---  Discord scheduler end  ---')


def postBlynk():
    logging.info('--- Blynk scheduler start ---')
    page = get_page(isn_url)
    isn, flux_10cm, Kp, epoch, date = extract_data(page)

    # blynk.virtual_write(31, isn)
    # blynk.virtual_write(32, flux_10cm)
    # blynk.virtual_write(33, Kp)

    def pinurl(pin, metric):
        pinUrl = BLYNK_API_URL + '/' + BLYNK_TOKEN + \
            '/update/' + pin + '?value=' + metric
        return pinUrl

    pinUrl = pinurl('V31', isn)
    requests.get(pinUrl, verify=False)

    pinUrl = pinurl('V32', flux_10cm)
    requests.get(pinUrl, verify=False)

    pinUrl = pinurl('V33', Kp)
    requests.get(pinUrl, verify=False)

    logging.info('Posted to Blynk: ISN, Flux, Kp; %s %s %s',
                 isn, flux_10cm, Kp)
    logging.info('---  Blynk scheduler end  ---')


sched = BackgroundScheduler(daemon=True)
# Schedule the ingestion every 6 hours
sched.add_job(func=dailyIsnIngest, trigger='interval', hours=6)
# Schedule posting to discord every 12 hours
sched.add_job(func=dailyIsnDiscord, trigger='interval', hours=24)
# Schedule posting to Blynk
sched.add_job(func=postBlynk, trigger='interval', minutes=29)
# start all schedulers
sched.start()
# Log all sched jobs
logging.info(sched.print_jobs(out=sys.stdout))

# app = Flask(__name__)
# app = FastAPI()

# Url to get ISN data from
isn_url = 'http://sunspotwatch.com'

# Splunk test url and headers
splunkurl = 'https://splunk.home:8088/services/collector/event?sourcetype=isn_daily'
splunkheaders = {
    'Authorization': 'Splunk 0dffc34c-268f-4b38-88a2-9f3e67498f2c'}

# Splunk index
index = 'isn'

# Elasticearch params & headers
esurl = 'http://elasticsearch.home:9200/solar/_doc/'
esheaders = {'Content-Type': 'application/json'}

# Get webpage


def get_page(url):
    logging.info('Trying to get metrics from page...')
    try:
        r = requests.get(url)
        r.raise_for_status()
        page = r.text
        logging.info('Page %s loaded ok. %s', url, r)
        return page
    except requests.exceptions.HTTPError as err:
        logging.error('Page %s load failed. %s Error: %s', url, r, err)
    except Exception as e:
        logging.error('Page load, some other error: %s', e)


def extract_data(page):
    try:
        logging.info('Extracting page data...')
        match = re.search(
            r"Sun.Spots\:\s\<b\>(\d+)\<\/b\>.as.of\s(\d+\/\d+\/\d+)", page)
        isn = match.group(1)
        date = match.group(2)
        match = re.search(r"10\.7\-cm\sFlux\:\s\<b\>(\d+)", page)
        flux_10cm = match.group(1)

        try:
            match = re.search(
                r"Planetary K-index\s\(\<b\>Kp\<\/b\>\)\:\s\<b\>(\d+)", page)
            Kp = match.group(1)
        except Exception as e:
            logging.error('Could not extract KP, setting to 0, {}'.format(e))
            Kp = str(0)

        date_object = datetime.strptime(date, '%m/%d/%Y')
        epoch = time.mktime(date_object.timetuple())
        esdate_object = date_object.strftime('%Y-%m-%dT%H:%M:%S')
        logging.debug('Daily ISN Count: %s', isn)
        logging.debug('Daily 10.7cm Flux: %s', flux_10cm)
        logging.debug('Daily Kp Index: %s', Kp)
    except AttributeError as e:
        logging.error('Attribute Error: %s', e)
    except UnboundLocalError as e:
        logging.error('Unbound Local Error: %s', e)
    except Exception as e:
        logging.error('Extract data, other error: %s', e)
    else:
        return isn, flux_10cm, Kp, epoch, esdate_object

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
        logging.error('Page load, some other error: %s', e)
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
        logging.error('Page load, some other error: %s', e)
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
        logging.error('Page load, some other error: %s', e)
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
    logging.info('Solar data enpoint response to client: %s',
                 request.client.host)
    page = get_page(isn_url)
    isn, flux_10cm, Kp, epoch, date = extract_data(page)
    daily = dict(isn=isn, flux_10cm=flux_10cm, Kp=Kp, date=date)
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
