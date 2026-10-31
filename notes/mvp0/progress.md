# Progress on the FN slice

- 2026-10-30: re-rating and seed scraping done; findings.json, reference doc and one-pager updated
- 2026-10-30: architecture v1 written; six independent Opus reviews, all "build after fixes"; architecture v2 written with every fix and the four disagreements settled
- 2026-10-30: build plan written; Opus plan review running
- 2026-10-30: plan review found 10 issues (undefined success measure, no cross-lane fusion, task 1 too big, seed mapping gaps, untested tie coverage, weak tests, forms need python-multipart); all fixed in architecture 2.1 and the plan; OpenAlex key confirmed working in the Authorization header
- 2026-10-30: task 0 found 5 of 9 GS-02/GS-10 picks reachable through OpenAlex; success measure restated on reach.json; place ranks, never filters (Baeyens' newest OpenAlex affiliation is Novi, MI)
- 2026-10-30: task 0 done after 2 review rounds; the question's own chips (telecom, 6G research) reach no GS-02 pick through OpenAlex, so reach is 4 of 9 (all GS-10) and the success measure is 3 of those 4; tasks 1a to 1c building
- 2026-10-30: tasks 1a, 1b, 1c done and reviewed (50 tests pass); live hand check: 'Who knows offshore wind near Boston?' -> topic 'offshore wind', place 'Boston' (metro) in 5 s; tasks 2 and 3 building
- 2026-10-30: tasks 2 and 3 done and reviewed (91 tests); live GS-10: de Wit #4, Janjevic #5, Goemans #8, Lermusiaux cut at OpenAlex rank 167 (HIT_LIMIT 100, kept as is: scoring is the real fix); task 2 adapted 5 existing tests that assumed a one-step search (assertions on the parse step unchanged); tasks 4 and 5 building
- 2026-10-30: tasks 4 and 5 done and reviewed; all 28 gold cases ran: dev 3 of 4 reachable found (target met), held-out 0 of 23, other 0 of 67; 2 cases failed at parse on off-by-one spans, fixed (spans within 2 characters are moved onto the chip text and logged), with a test that fails without the fix; still to do: final whole-code review, rerun of all 28, done-check screenshots
