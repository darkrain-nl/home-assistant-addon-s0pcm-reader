"""
Tests for measurement data reading and processing logic.
"""
import pytest
import json
import os
import datetime
import importlib
from unittest.mock import MagicMock, patch


def test_read_measurement_id_conversion(temp_config_dir, mocker):
    """Test that meter IDs are converted from strings to integers."""
    import s0pcm_reader
    importlib.reload(s0pcm_reader)
    
    # measurement: { "1": { ... } } should become { 1: { ... } }
    sample_data = {
        "date": "2026-01-24",
        "1": {"total": 100, "pulsecount": 10}
    }
    
    measurement_path = os.path.join(temp_config_dir, 'measurement.json')
    with open(measurement_path, 'w') as f:
        json.dump(sample_data, f)
        
    s0pcm_reader.measurementname = measurement_path
    s0pcm_reader.ReadMeasurement()
    
    # Meter 1 should be an integer key now
    assert 1 in s0pcm_reader.measurement
    assert "1" not in s0pcm_reader.measurement
    assert s0pcm_reader.measurement[1]['total'] == 100

def test_read_measurement_date_parsing(temp_config_dir, mocker):
    """Test different date formats in measurement.json."""
    import s0pcm_reader
    importlib.reload(s0pcm_reader)
    
    # 1. Standard string date
    sample_data = {"date": "2026-01-20"}
    measurement_path = os.path.join(temp_config_dir, 'measurement.json')
    
    with open(measurement_path, 'w') as f:
        json.dump(sample_data, f)
    
    s0pcm_reader.measurementname = measurement_path
    s0pcm_reader.ReadMeasurement()
    assert isinstance(s0pcm_reader.measurement['date'], datetime.date)
    assert s0pcm_reader.measurement['date'].year == 2026

def test_read_measurement_missing_file(temp_config_dir, mocker):
    """Test behavior when measurement.json is missing."""
    import s0pcm_reader
    importlib.reload(s0pcm_reader)
    
    # Point to a non-existent file
    s0pcm_reader.measurementname = os.path.join(temp_config_dir, 'no_such_file.json')
    s0pcm_reader.ReadMeasurement()
    
    # Should default to today's date and empty dict
    assert isinstance(s0pcm_reader.measurement['date'], datetime.date)
    assert s0pcm_reader.measurement['date'] == datetime.date.today()

def test_read_measurement_invalid_json(temp_config_dir, mocker):
    """Test behavior when measurement.json is corrupt."""
    import s0pcm_reader
    importlib.reload(s0pcm_reader)
    
    measurement_path = os.path.join(temp_config_dir, 'corrupt.json')
    with open(measurement_path, 'w') as f:
        f.write("this is not json")
        
    s0pcm_reader.measurementname = measurement_path
    s0pcm_reader.ReadMeasurement()
    
    # Should recover with defaults
    assert isinstance(s0pcm_reader.measurement['date'], datetime.date)

def test_read_measurement_not_a_dict(temp_config_dir, mocker):
    """Test behavior when measurement.json contains a list instead of a dict."""
    import s0pcm_reader
    importlib.reload(s0pcm_reader)
    
    measurement_path = os.path.join(temp_config_dir, 'list.json')
    with open(measurement_path, 'w') as f:
        json.dump(["this", "is", "a", "list"], f)
        
    s0pcm_reader.measurementname = measurement_path
    s0pcm_reader.ReadMeasurement()
    
    # Should recover with defaults
    assert isinstance(s0pcm_reader.measurement, dict)
    assert 'date' in s0pcm_reader.measurement

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
