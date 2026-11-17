CREATE TEMP TABLE died_ranks AS
SELECT d.search_id, d.person_id,
       (SELECT count(*) FROM candidates c WHERE c.search_id = d.search_id AND c.section = d.section
          AND c.cut_reason IS NOT NULL)
       + row_number() OVER (PARTITION BY d.search_id, d.section ORDER BY d.rank) AS cut_rank
FROM candidates d WHERE d.aside = 'died' AND d.cut_reason IS NULL;
UPDATE candidates SET cut_reason = 'died', aside = NULL,
    rank = (SELECT cut_rank FROM died_ranks r WHERE r.search_id = candidates.search_id AND r.person_id = candidates.person_id)
WHERE aside = 'died' AND cut_reason IS NULL;
UPDATE candidates SET aside = NULL WHERE aside = 'died';
DROP TABLE died_ranks;
