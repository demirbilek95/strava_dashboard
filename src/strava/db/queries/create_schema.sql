-- Strava Activity Database Schema
-- SQLite database for storing activity summaries and detailed stream data

-- Main activities table (from CSV)
CREATE TABLE IF NOT EXISTS activities (
    activity_id INTEGER PRIMARY KEY,
    activity_date TIMESTAMP NOT NULL,
    activity_name TEXT,
    activity_type TEXT,
    activity_description TEXT,
    
    -- Time metrics (in seconds)
    elapsed_time INTEGER,
    moving_time INTEGER,
    
    -- Distance metrics (in meters for consistency)
    distance REAL,
    
    -- Speed metrics
    max_speed REAL,
    average_speed REAL,
    
    -- Elevation metrics (in meters)
    elevation_gain REAL,
    elevation_loss REAL,
    elevation_low REAL,
    elevation_high REAL,
    max_grade REAL,
    average_grade REAL,
    
    -- Heart rate metrics (bpm)
    max_heart_rate INTEGER,
    average_heart_rate INTEGER,
    
    -- Cadence metrics
    max_cadence INTEGER,
    average_cadence INTEGER,
    
    -- Power metrics (watts)
    max_watts INTEGER,
    average_watts INTEGER,
    weighted_average_power INTEGER,
    
    -- Energy metrics
    calories INTEGER,
    relative_effort INTEGER,
    total_work INTEGER,
    
    -- Temperature metrics (celsius)
    max_temperature REAL,
    average_temperature REAL,
    
    -- Other metrics
    athlete_weight REAL,
    commute BOOLEAN DEFAULT 0,
    gear TEXT,
    filename TEXT,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Detailed activity streams table (from TCX/FIT files)
CREATE TABLE IF NOT EXISTS activity_streams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL,
    
    -- Temporal data
    timestamp TIMESTAMP NOT NULL,
    elapsed_seconds REAL,  -- Seconds from start of activity
    
    -- GPS coordinates (decimal degrees)
    latitude REAL,
    longitude REAL,
    
    -- Movement metrics
    distance REAL,  -- Cumulative distance in meters
    speed REAL,  -- Speed in m/s
    enhanced_speed REAL,  -- High-precision speed (FIT only)
    pace REAL,  -- Pace in min/km (calculated)
    
    -- Physiological metrics
    heart_rate INTEGER,  -- BPM
    cadence INTEGER,  -- Steps/min (run) or RPM (bike)
    
    -- Spatial metrics
    altitude REAL,  -- Meters
    enhanced_altitude REAL,  -- High-precision altitude (FIT only)
    
    -- Advanced metrics (may not be available in all activities)
    power INTEGER,  -- Watts
    accumulated_power INTEGER,  -- Total power (FIT only)
    temperature INTEGER,  -- Celsius (FIT only)
    step_length REAL,  -- Meters (FIT only)
    
    -- Metadata
    source_type TEXT,  -- 'TCX' or 'FIT'
    
    FOREIGN KEY (activity_id) REFERENCES activities(activity_id) ON DELETE CASCADE
);

-- Indexes for efficient querying

-- Activity indexes
CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(activity_date);
CREATE INDEX IF NOT EXISTS idx_activities_type ON activities(activity_type);
CREATE INDEX IF NOT EXISTS idx_activities_type_date ON activities(activity_type, activity_date);
CREATE INDEX IF NOT EXISTS idx_activities_commute ON activities(commute);

-- Stream indexes
CREATE INDEX IF NOT EXISTS idx_streams_activity ON activity_streams(activity_id);
CREATE INDEX IF NOT EXISTS idx_streams_timestamp ON activity_streams(activity_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_streams_location ON activity_streams(latitude, longitude) 
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

-- Views for common queries

-- View for activities with stream data available
CREATE VIEW IF NOT EXISTS activities_with_streams AS
SELECT DISTINCT a.*
FROM activities a
INNER JOIN activity_streams s ON a.activity_id = s.activity_id;

-- View for quick summary statistics
CREATE VIEW IF NOT EXISTS activity_summary_stats AS
SELECT 
    activity_type,
    COUNT(*) as total_activities,
    SUM(distance) as total_distance_m,
    SUM(moving_time) as total_moving_time_s,
    AVG(average_heart_rate) as avg_heart_rate,
    AVG(average_speed) as avg_speed_ms
FROM activities
WHERE activity_type IS NOT NULL
GROUP BY activity_type;
