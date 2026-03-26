-- Get planned workouts for a date range, with matched activity data
SELECT
    w.workout_id,
    w.plan_id,
    w.workout_date,
    w.workout_type,
    w.description,
    w.target_distance_km,
    w.target_duration_min,
    w.target_pace_min_km,
    w.target_hr_zone,
    w.completed,
    w.matched_activity_id,
    w.feedback,
    a.activity_name,
    a.activity_type AS actual_type,
    a.distance / 1000.0 AS actual_distance_km,
    a.moving_time AS actual_moving_time,
    a.average_heart_rate AS actual_avg_hr,
    a.elevation_gain AS actual_elevation
FROM planned_workouts w
LEFT JOIN activities a ON w.matched_activity_id = a.activity_id
WHERE w.plan_id = ?
ORDER BY w.workout_date ASC;
