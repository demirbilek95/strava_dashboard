-- Get the active training plan with its workouts
SELECT
    p.plan_id,
    p.goal,
    p.start_date,
    p.end_date,
    p.status,
    p.created_at,
    p.raw_llm_response,
    w.workout_id,
    w.workout_date,
    w.workout_type,
    w.description,
    w.target_distance_km,
    w.target_duration_min,
    w.target_pace_min_km,
    w.target_hr_zone,
    w.completed,
    w.matched_activity_id,
    w.feedback
FROM training_plans p
LEFT JOIN planned_workouts w ON p.plan_id = w.plan_id
WHERE p.status = 'active'
  AND (? IS NULL OR p.athlete_id = ?)
ORDER BY p.created_at DESC, w.workout_date ASC;
