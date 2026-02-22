"""Generate NFO files for Jellyfin with Romanian metadata"""
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET
from xml.dom import minidom

def create_tvshow_nfo(show_data: dict, nfo_path: Path) -> bool:
    """Create tvshow.nfo for Jellyfin"""
    try:
        root = ET.Element('tvshow')
        
        ET.SubElement(root, 'title').text = show_data.get('name', '')
        ET.SubElement(root, 'originaltitle').text = show_data.get('original_name', '')
        
        if show_data.get('overview'):
            ET.SubElement(root, 'plot').text = show_data['overview']
        
        if show_data.get('first_air_date'):
            ET.SubElement(root, 'premiered').text = show_data['first_air_date']
            ET.SubElement(root, 'year').text = show_data['first_air_date'][:4]
        
        ET.SubElement(root, 'tmdbid').text = str(show_data.get('id', ''))
        
        for genre in show_data.get('genres', []):
            ET.SubElement(root, 'genre').text = genre.get('name', '')
        
        # Pretty print
        xml_str = minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")
        nfo_path.write_text(xml_str)
        return True
    except Exception as e:
        print(f"Error creating tvshow.nfo: {e}")
        return False

def create_episode_nfo(episode_data: dict, nfo_path: Path) -> bool:
    """Create episode NFO for Jellyfin"""
    try:
        root = ET.Element('episodedetails')
        
        ET.SubElement(root, 'title').text = episode_data.get('name', '')
        
        if episode_data.get('overview'):
            ET.SubElement(root, 'plot').text = episode_data['overview']
        
        ET.SubElement(root, 'season').text = str(episode_data.get('season_number', ''))
        ET.SubElement(root, 'episode').text = str(episode_data.get('episode_number', ''))
        
        if episode_data.get('air_date'):
            ET.SubElement(root, 'aired').text = episode_data['air_date']
        
        # Pretty print
        xml_str = minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")
        nfo_path.write_text(xml_str)
        return True
    except Exception as e:
        print(f"Error creating episode NFO: {e}")
        return False

def create_movie_nfo(movie_data: dict, nfo_path: Path) -> bool:
    """Create movie NFO for Jellyfin"""
    try:
        root = ET.Element('movie')
        
        ET.SubElement(root, 'title').text = movie_data.get('title', '')
        ET.SubElement(root, 'originaltitle').text = movie_data.get('original_title', '')
        
        if movie_data.get('overview'):
            ET.SubElement(root, 'plot').text = movie_data['overview']
        
        if movie_data.get('release_date'):
            ET.SubElement(root, 'premiered').text = movie_data['release_date']
            ET.SubElement(root, 'year').text = movie_data['release_date'][:4]
        
        ET.SubElement(root, 'tmdbid').text = str(movie_data.get('id', ''))
        
        for genre in movie_data.get('genres', []):
            ET.SubElement(root, 'genre').text = genre.get('name', '')
        
        # Pretty print
        xml_str = minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")
        nfo_path.write_text(xml_str)
        return True
    except Exception as e:
        print(f"Error creating movie NFO: {e}")
        return False
