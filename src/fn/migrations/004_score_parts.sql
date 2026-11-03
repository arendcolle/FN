ALTER TABLE candidates DROP COLUMN tie_json;
ALTER TABLE candidates ADD COLUMN score_parts_json TEXT NOT NULL DEFAULT '[]';
