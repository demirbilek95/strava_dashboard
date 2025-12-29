-- Query to fetch all activities with their metrics
-- Returns database column names directly (snake_case)
SELECT 
    activity_id,
    activity_date,
    activity_name,
    activity_type,
    activity_description,
    elapsed_time,
    moving_time,
    distance / 1000.0 as distance,  -- Convert meters to km for convenience
    max_speed,
    average_speed,
    elevation_gain,
    elevation_loss,
    elevation_low,
    elevation_high,
    max_grade,
    average_grade,
    max_heart_rate,
    average_heart_rate,
    max_cadence,
    average_cadence,
    max_watts,
    average_watts,
    weighted_average_power,
    calories,
    relative_effort,
    total_work,
    max_temperature,
    average_temperature,
    athlete_weight,
    commute,
    gear,
    filename
FROM activities
ORDER BY activity_date DESC
