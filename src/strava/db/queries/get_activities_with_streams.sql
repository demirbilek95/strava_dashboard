-- Query to get list of activities that have stream data available
SELECT DISTINCT activity_id 
FROM activity_streams 
ORDER BY activity_id DESC
