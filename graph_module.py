from data_urls import ISN_URL, KP_URL, SOLAR_CYCLE_IMAGE_URL
import asyncio
import logging
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx
from datetime import datetime
from collections import defaultdict
import json
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")

# --- Constants ---
CACHE_FILE = 'solar_data_cache.json'
CACHE_DURATION_SECONDS = 60  # 1 min cache duration for more frequent updates
CACHE_VERSION = 3

# --- Helper Functions ---


def flux_to_isn(flux):
    """Converts F10.7cm flux to an estimated International Sunspot Number (ISN).

    Formula: ISN ≈ (1.14 * flux) - 73.21
    """
    return max(0, int(1.14 * flux - 73.21))


async def fetch_json(client, url):
    """Fetches JSON data from a URL."""
    try:
        response = await client.get(url)
        response.raise_for_status()
        logger.info(f"Successfully fetched data from {url}")
        return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching {url}: {e}")
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
    return None


def process_flux_data(flux_raw_data):
    """Processes raw flux data to get daily averages."""
    daily_flux = defaultdict(lambda: {'sum': 0, 'count': 0})
    if not flux_raw_data:
        return {}

    for item in flux_raw_data:
        try:
            # Handle different possible time formats
            time_tag_str = item.get('time_tag', '').split('T')[0]
            if not time_tag_str:
                continue

            date_obj = datetime.strptime(time_tag_str, '%Y-%m-%d').date()
            flux = float(item.get('flux', 0))

            daily_flux[date_obj]['sum'] += flux
            daily_flux[date_obj]['count'] += 1
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not process flux item: {item}. Error: {e}")
            continue

    processed = {
        date.strftime('%Y-%m-%d'): data['sum'] / data['count']
        for date, data in daily_flux.items() if data['count'] > 0
    }
    return processed


def process_kp_data(kp_raw_data):
    """Processes raw Kp data to get daily averages and retain individual measurements."""
    daily_kp = defaultdict(lambda: {'sum': 0, 'count': 0})
    measurements = []

    if not kp_raw_data:
        return {}, []

    for item in kp_raw_data:
        time_full = item.get('time_tag')
        if not time_full:
            continue

        time_parts = time_full.split('T')
        time_tag_str = time_parts[0] if time_parts else ''
        if not time_tag_str:
            continue

        kp_value = item.get('kp_index')
        if kp_value is None:
            kp_value = item.get('estimated_kp')

        if kp_value is None:
            continue

        try:
            kp = float(kp_value)
        except (ValueError, TypeError) as e:
            logger.warning(f"Could not convert Kp value to float: {kp_value}. Error: {e}")
            continue

        try:
            date_obj = datetime.strptime(time_tag_str, '%Y-%m-%d').date()
        except ValueError as e:
            logger.warning(f"Could not parse Kp date: {time_tag_str}. Error: {e}")
            continue

        daily_kp[date_obj]['sum'] += kp
        daily_kp[date_obj]['count'] += 1

        measurements.append({
            "timestamp": time_full,
            "value": round(kp, 2)
        })

    processed = {
        date.strftime('%Y-%m-%d'): data['sum'] / data['count']
        for date, data in daily_kp.items() if data['count'] > 0
    }

    measurements.sort(key=lambda entry: entry["timestamp"])

    return processed, measurements


def get_cached_data():
    """Reads data from the cache file if it's recent."""
    if os.path.exists(CACHE_FILE):
        try:
            file_mod_time = os.path.getmtime(CACHE_FILE)
            if (datetime.now().timestamp() - file_mod_time) < CACHE_DURATION_SECONDS:
                with open(CACHE_FILE, 'r') as f:
                    cached = json.load(f)
                    if cached.get("cache_version") == CACHE_VERSION:
                        logger.info("Serving data from cache.")
                        return cached
                    logger.info("Ignoring stale cache due to version mismatch.")
                    try:
                        os.remove(CACHE_FILE)
                        logger.info("Removed stale cache file.")
                    except OSError as remove_error:
                        logger.warning(f"Could not remove stale cache file: {remove_error}")
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Error reading cache file: {e}")
    return None


def save_data_to_cache(data):
    """Saves processed data to the cache file."""
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f)
        logger.info(f"Successfully saved data to cache file: {CACHE_FILE}")
    except OSError as e:
        logger.error(f"Error saving data to cache file: {e}")

# --- FastAPI Endpoint ---


@router.get("/", response_class=HTMLResponse)
async def graph_page(request: Request):
    """Serves the graph page with solar data."""

    cached_data = get_cached_data()
    if cached_data:
        return templates.TemplateResponse(
            "graph.html",
            {
                "request": request,
                "solar_data": cached_data,
                "solar_cycle_image": SOLAR_CYCLE_IMAGE_URL,
            },
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        flux_task = fetch_json(client, ISN_URL)
        kp_task = fetch_json(client, KP_URL)
        flux_raw_data, kp_raw_data = await asyncio.gather(flux_task, kp_task)

    if not flux_raw_data:
        return HTMLResponse("Could not fetch solar flux data.", status_code=500)

    # Process data
    daily_flux_avg = process_flux_data(flux_raw_data)
    daily_kp_avg, kp_measurements = process_kp_data(kp_raw_data)

    # Combine data, using flux dates as the primary source
    sorted_dates = sorted(daily_flux_avg.keys())

    final_data = {
        "dates": [],
        "flux": [],
        "isn": [],
        "kp": [],
        "kp_points": [],
        "kp_dates": [],
        "kp_daily": [],
        "cache_version": CACHE_VERSION
    }

    for date_str in sorted_dates:
        flux_val = daily_flux_avg[date_str]

        final_data["dates"].append(date_str)
        final_data["flux"].append(round(flux_val, 2))
        final_data["isn"].append(flux_to_isn(flux_val))

    kp_dates_sorted = sorted(daily_kp_avg.keys())
    final_data["kp_dates"] = kp_dates_sorted
    final_data["kp_daily"] = [
        round(daily_kp_avg[date_key], 2) for date_key in kp_dates_sorted
    ]
    final_data["kp"] = list(final_data["kp_daily"])  # backward compatibility

    final_data["kp_points"] = kp_measurements

    # Add timestamp for when data was last updated
    final_data["last_updated"] = datetime.now().isoformat()

    logger.info(f"Processed data for {len(final_data['dates'])} dates.")
    if final_data["dates"]:
        logger.info(f"Date range: {final_data['dates'][0]} to {final_data['dates'][-1]}")

    save_data_to_cache(final_data)

    return templates.TemplateResponse(
        "graph.html",
        {
            "request": request,
            "solar_data": final_data,
            "solar_cycle_image": SOLAR_CYCLE_IMAGE_URL,
        },
    )
