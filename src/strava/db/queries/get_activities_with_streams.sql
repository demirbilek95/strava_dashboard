-- Query to get list of activities that have stream data available
SELECT DISTINCT a.* 
FROM activities a
INNER JOIN activity_streams s ON a.activity_id = s.activity_id
ORDER BY a.activity_date DESC
