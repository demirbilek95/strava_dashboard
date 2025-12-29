-- Query to get detailed stream data for a specific activity
-- Parameter: activity_id (passed as ? in prepared statement)
SELECT * 
FROM activity_streams 
WHERE activity_id = ? 
ORDER BY timestamp
