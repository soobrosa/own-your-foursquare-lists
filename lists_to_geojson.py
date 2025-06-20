import json
import os
import glob
import logging
import duckdb
import re

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def sanitize_filename(name):
    # Replace invalid filename characters with underscores
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Remove leading/trailing spaces and dots
    sanitized = sanitized.strip('. ')
    # Replace multiple spaces/underscores with a single underscore
    sanitized = re.sub(r'[\s_]+', '_', sanitized)
    # Truncate to reasonable length (e.g., 100 chars)
    return sanitized[:100]

# Load tips data
logging.info("Loading tips data...")
with open('output/tips_extracted.json', 'r', encoding='utf-8') as f:
    tips_data = json.load(f)

# Create a dictionary of tips by venue ID
venue_tips = {}
for tip in tips_data:
    venue_id = tip['venue.id']
    if venue_id not in venue_tips:
        venue_tips[venue_id] = []
    venue_tips[venue_id].append(tip['text'])

logging.info(f"Loaded tips for {len(venue_tips)} venues")

# Load the lists JSON file
file_path = 'input/lists.json'

# Read the JSON data
with open(file_path, 'r') as file:
    lists_data = json.load(file)

# Use the 'items' key for the actual lists
lists = lists_data["items"]

# First collect all venue IDs from lists
list_venue_ids = set()
for list_item in lists:
    list_items = list_item.get('listItems', {}).get('items', [])
    for item in list_items:
        venue = item.get('venue')
        if venue and 'id' in venue:
            list_venue_ids.add(venue['id'])

logging.info(f"Found {len(list_venue_ids)} unique venue IDs in lists")

# Create DuckDB connection and load fused data first
con = duckdb.connect(database=':memory:')
logging.info("Loading fused places data into DuckDB...")

# Create a temporary table with the IDs we need
con.execute("""
    CREATE TABLE needed_venues AS 
    SELECT unnest(?) as id
""", [list(list_venue_ids)])

# Query venues from parquet files

fused_venues = con.execute(f"""
    SELECT DISTINCT 
        fsq_place_id as id, 
        latitude, 
        longitude,
        address,
        website,
        fsq_category_labels
    FROM read_parquet('s3://fsq-os-places-us-east-1/release/dt=2025-06-10/places/parquet/*')
    WHERE fsq_place_id IN (SELECT id FROM needed_venues)
    AND latitude IS NOT NULL 
    AND longitude IS NOT NULL
    AND latitude BETWEEN -90 AND 90
    AND longitude BETWEEN -180 AND 180
""").fetchall()

# Initialize venue_coords with fused data
venue_coords = {}
for venue in fused_venues:
    venue_id = str(venue[0])
    venue_coords[venue_id] = {
        'lat': float(venue[1]),
        'lng': float(venue[2]),
        'address': str(venue[3] or ''),
        'website': str(venue[4] or ''),
        'categories': venue[5] if venue[5] else [],
        'source': 'fused_places',
        'tips': venue_tips.get(venue_id, [])  # Add tips to venue data
    }

logging.info(f"Found {len(fused_venues)} venues in fused data")

# Add check-in data only for venues not found in fused data
missing_venue_ids = list(list_venue_ids - set(venue_coords.keys()))
if missing_venue_ids:
    logging.info(f"Looking up {len(missing_venue_ids)} missing venues in check-in data")
    
    checkins_files = sorted(glob.glob('input/checkins*.json'))
    for checkins_file in checkins_files:
        logging.info(f"Processing checkins file: {checkins_file}")
        with open(checkins_file, 'r') as f:
            data = json.load(f)
            items = data['items'] if isinstance(data, dict) and 'items' in data else data
            for item in items:
                venue = item.get('venue')
                if not venue or 'id' not in venue:
                    continue
                venue_id = venue['id']
                if venue_id not in missing_venue_ids:
                    continue
                lat = item.get('lat')
                lng = item.get('lng')
                if lat is not None and lng is not None:
                    # Validate coordinates
                    if -90 <= lat <= 90 and -180 <= lng <= 180:
                        # Only add if we don't have coordinates from fused data
                        if venue_id not in venue_coords:
                            venue_coords[venue_id] = {
                                'lat': lat,
                                'lng': lng,
                                'source': 'checkins'
                            }
                    else:
                        logging.warning(f"Invalid coordinates for venue {venue_id}: lat={lat}, lng={lng}")

# Create output directory if it doesn't exist
output_dir = os.path.join('output', 'geojson')
os.makedirs(output_dir, exist_ok=True)

# Process each list
for list_item in lists:
    list_id = list_item['id']
    list_name = list_item['name']
    
    # Extract venues from listItems['items']
    list_items = list_item.get('listItems', {}).get('items', [])
    if not list_items:
        logging.warning(f"List {list_id} ({list_name}) has no venues")
        continue
    
    # Convert to GeoJSON format
    geojson = {
        "type": "FeatureCollection",
        "features": []
    }

    venues_with_coords = 0
    venues_without_coords = 0

    for item in list_items:
        venue = item.get('venue')
        if not venue:
            continue
        # Try to get coordinates from venue['location']
        lat = venue.get('location', {}).get('lat') if 'location' in venue else None
        lng = venue.get('location', {}).get('lng') if 'location' in venue else None
        coord_source = 'venue_location'
        
        # If missing, look up in our coordinate mapping
        if (lat is None or lng is None) and venue.get('id') in venue_coords:
            lat = venue_coords[venue['id']]['lat']
            lng = venue_coords[venue['id']]['lng']
            coord_source = venue_coords[venue['id']]['source']

        if lat is not None and lng is not None:
            # Validate coordinates
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                feature = {
                    "type": "Feature",
                    "properties": {
                        "name": venue.get('name', ''),
                        "id": venue.get('id', ''),
                        "list_id": list_id,
                        "list_name": list_name,
                        "url": venue.get('url', ''),
                        "address": venue_coords.get(venue.get('id'), {}).get('address', ''),
                        "website": venue_coords.get(venue.get('id'), {}).get('website', ''),
                        "categories": venue_coords.get(venue.get('id'), {}).get('categories', []),
                        "tips": venue_coords.get(venue.get('id'), {}).get('tips', []),  # Add tips to properties
                        "coord_source": coord_source
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [lng, lat]
                    }
                }
                # Add bucket and topic fields
                if feature["properties"]["categories"]:
                    first_category = feature["properties"]["categories"][0]
                    if '>' in first_category:
                        bucket = first_category.split('>')[0].strip()
                        topic = first_category.split('>')[-1].strip()
                        feature["properties"]["bucket"] = bucket
                        feature["properties"]["topic"] = topic
                    else:
                        feature["properties"]["bucket"] = first_category
                        feature["properties"]["topic"] = first_category
                else:
                    feature["properties"]["bucket"] = ""
                    feature["properties"]["topic"] = ""
                
                geojson["features"].append(feature)
                venues_with_coords += 1
            else:
                logging.warning(f"Invalid coordinates for venue {venue.get('id')} in list {list_id}: lat={lat}, lng={lng}")
                venues_without_coords += 1
        else:
            venues_without_coords += 1

    # Save GeoJSON file
    sanitized_list_name = sanitize_filename(list_name)
    geojson_path = os.path.join(output_dir, f"{sanitized_list_name}_{list_id}.geojson")
    with open(geojson_path, "w") as f:
        json.dump(geojson, f, indent=2)
    logging.info(f"Wrote {geojson_path} with {len(geojson['features'])} features. {venues_without_coords} venues without coordinates.")

print("GeoJSON files have been created in b_release/geojson/")
