import fs from 'fs';
import path from 'path';

export default function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const dataDir = path.join(process.cwd(), 'output/geojson');
    
    // Check if data directory exists
    if (!fs.existsSync(dataDir)) {
      return res.status(404).json({ error: 'Data directory not found' });
    }

    // Read all files in the data directory
    const files = fs.readdirSync(dataDir);
    
    // Filter for .geojson files only
    const geojsonFiles = files.filter(file => file.endsWith('.geojson'));
    
    // Sort files alphabetically
    geojsonFiles.sort();
    
    res.status(200).json(geojsonFiles);
  } catch (error) {
    console.error('Error reading GeoJSON files:', error);
    res.status(500).json({ error: 'Failed to read GeoJSON files' });
  }
} 