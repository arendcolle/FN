UPDATE searches SET chips_json = replace(chips_json, '"ror:https://ror.org/', '"ror:')
WHERE chips_json LIKE '%"ror:https://ror.org/%';
