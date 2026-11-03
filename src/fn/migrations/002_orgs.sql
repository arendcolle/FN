ALTER TABLE searches ADD COLUMN kind TEXT NOT NULL DEFAULT 'search';

CREATE TABLE orgs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    country_code TEXT,
    region TEXT,
    name_lang TEXT,
    source_id TEXT NOT NULL REFERENCES sources (id),
    fetched_at TEXT NOT NULL
);

UPDATE claims SET org_id = 'ror:05f950310' WHERE org_id = 'ku-leuven';
UPDATE claims SET org_id = 'ror:00cv9y106' WHERE org_id = 'ugent';
UPDATE claims SET org_id = 'ror:006e5kg04' WHERE org_id = 'vub';
UPDATE claims SET org_id = 'ror:008x57b05' WHERE org_id = 'uantwerpen';
UPDATE claims SET org_id = 'ror:04nbhqj75' WHERE org_id = 'uhasselt';
UPDATE claims SET org_id = 'ror:02kcbn207' WHERE org_id = 'imec';
UPDATE claims SET org_id = 'ror:03baec336' WHERE org_id = 'iminds';
UPDATE claims SET org_id = 'ror:04gq0w522' WHERE org_id = 'vito';
UPDATE claims SET org_id = 'ror:05cjt1n05' WHERE org_id = 'ilvo';
UPDATE claims SET org_id = 'ror:00j54wy13' WHERE org_id = 'inbo';
UPDATE claims SET org_id = 'wikidata:Q66058368' WHERE org_id = 'energyville';
UPDATE claims SET org_id = 'wikidata:Q1301699' WHERE org_id = 'kvab';
UPDATE claims SET org_id = 'ror:02495e989' WHERE org_id = 'uclouvain';
UPDATE claims SET org_id = 'ror:01r9htc13' WHERE org_id = 'ulb';
UPDATE claims SET org_id = 'ror:00afp2z80' WHERE org_id = 'uliege';
UPDATE claims SET org_id = 'ror:02qnnz951' WHERE org_id = 'umons';
UPDATE claims SET org_id = 'ror:03d1maw17' WHERE org_id = 'unamur';
UPDATE claims SET org_id = 'ror:058qm9p63' WHERE org_id = 'rmi';
UPDATE claims SET org_id = 'ror:03vfw8w96' WHERE org_id = 'bira-iasb';
UPDATE claims SET org_id = 'ror:02y22ws83' WHERE org_id = 'rbins';
UPDATE claims SET org_id = 'ror:02e2c7k09' WHERE org_id = 'tu-delft';
UPDATE claims SET org_id = 'ror:027bh9e22' WHERE org_id = 'leiden';
UPDATE claims SET org_id = 'ror:04pp8hn57' WHERE org_id = 'utrecht';
UPDATE claims SET org_id = 'ror:04dkp9463' WHERE org_id = 'uva';
UPDATE claims SET org_id = 'ror:04qw24q55' WHERE org_id = 'wageningen';
UPDATE claims SET org_id = 'ror:02c2kyt77' WHERE org_id = 'tu-eindhoven';
UPDATE claims SET org_id = 'ror:042nb2s44' WHERE org_id = 'mit';
UPDATE claims SET org_id = 'ror:03vek6s52' WHERE org_id = 'harvard';
UPDATE claims SET org_id = 'ror:00f54p054' WHERE org_id = 'stanford';
UPDATE claims SET org_id = 'ror:00hj8s172' WHERE org_id = 'columbia';
UPDATE claims SET org_id = 'ror:0190ak572' WHERE org_id = 'nyu';
UPDATE claims SET org_id = 'ror:01an7q238' WHERE org_id = 'uc-berkeley';
UPDATE claims SET org_id = 'ror:046rm7j60' WHERE org_id = 'ucla';
UPDATE claims SET org_id = 'ror:02t274463' WHERE org_id = 'ucsb';
UPDATE claims SET org_id = 'ror:0168r3w48' WHERE org_id = 'ucsd';
UPDATE claims SET org_id = 'ror:043mz5j54' WHERE org_id = 'ucsf';
UPDATE claims SET org_id = 'ror:05rrcem69' WHERE org_id = 'uc-davis';
UPDATE claims SET org_id = 'ror:03v76x132' WHERE org_id = 'yale';
UPDATE claims SET org_id = 'ror:024mw5h28' WHERE org_id = 'uchicago';
UPDATE claims SET org_id = 'ror:00hx57361' WHERE org_id = 'princeton';
UPDATE claims SET org_id = 'ror:01zkghx44' WHERE org_id = 'georgia-tech';
UPDATE claims SET org_id = 'ror:05vzafd60' WHERE org_id = 'georgetown';
UPDATE claims SET org_id = 'ror:05bnh6r87' WHERE org_id = 'cornell';
UPDATE claims SET org_id = 'ror:00jmfr291' WHERE org_id = 'umich';
UPDATE claims SET org_id = 'ror:00py81415' WHERE org_id = 'duke';
UPDATE claims SET org_id = 'ror:05qwgg493' WHERE org_id = 'boston-u';
UPDATE claims SET org_id = 'ror:000e0be47' WHERE org_id = 'northwestern';
UPDATE claims SET org_id = 'ror:00cvxb145' WHERE org_id = 'uw';
UPDATE claims SET org_id = 'ror:00za53h95' WHERE org_id = 'jhu';
UPDATE claims SET org_id = 'ror:00b30xv10' WHERE org_id = 'upenn';
UPDATE claims SET org_id = 'ror:05x2bcf33' WHERE org_id = 'cmu';
UPDATE claims SET org_id = 'ror:0153tk833' WHERE org_id = 'uva-us';
UPDATE claims SET org_id = 'ror:05gq02987' WHERE org_id = 'brown';
UPDATE claims SET org_id = 'ror:01cwqze88' WHERE org_id = 'nih';
UPDATE claims SET org_id = 'ror:047s2c258' WHERE org_id = 'umd';
UPDATE claims SET org_id = 'ror:03taz7m60' WHERE org_id = 'usc';
UPDATE claims SET org_id = 'ror:04a9tmd77' WHERE org_id = 'mount-sinai';
UPDATE claims SET org_id = 'ror:02tvcev59' WHERE org_id = 'new-school';
UPDATE claims SET org_id = 'ror:017zqws13' WHERE org_id = 'umn';
UPDATE claims SET org_id = 'ror:014rsed66' WHERE org_id = 'baef';
UPDATE claims SET org_id = 'ror:00m1rny06' WHERE org_id = 'francqui';
UPDATE claims SET org_id = 'wikidata:Q117190825' WHERE org_id = 'belgian-climate-centre';
UPDATE claims SET org_id = 'wikidata:Q31' WHERE org_id = 'belgium';
-- Any other old internal id has no new id, so it becomes empty rather than stale.
UPDATE claims SET org_id = NULL WHERE org_id NOT LIKE 'ror:%' AND org_id NOT LIKE 'wikidata:%';
