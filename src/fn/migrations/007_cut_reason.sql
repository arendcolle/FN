UPDATE candidates SET cut_reason = 'no_belgian_evidence'
WHERE section = 'new' AND cut_reason IS NULL
  AND (SELECT group_concat(key) FROM json_each(lane_ranks_json)) = 'openalex'
  AND NOT EXISTS (SELECT 1 FROM json_each(score_parts_json) WHERE json_extract(value, '$.feature') = 'belgian_years');
