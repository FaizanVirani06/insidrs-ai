-- Study 3, amendment 3(a): verify how 10b5-1 plans appear in the Form 4 XML before extraction.
-- Read-only. Counts only; no returns are touched.
SET default_transaction_read_only = on;

SELECT LEFT(filing_date,4) AS yr, COUNT(*) AS filings,
       COUNT(*) FILTER (WHERE xml_text ~* '10b5.?1') AS mentions_10b5_1,
       COUNT(*) FILTER (WHERE xml_text ~* '<[A-Za-z0-9_]*10b5[A-Za-z0-9_]*[^>]*>') AS has_10b5_element,
       COUNT(*) FILTER (WHERE xml_text ~* '<[A-Za-z0-9_]*10b5[A-Za-z0-9_]*[^>]*>\s*(1|true)\s*</') AS element_true,
       COUNT(*) FILTER (WHERE xml_text ~* '(not|no)\s+([a-z]+\s+){0,4}pursuant\s+to\s+(a\s+)?(rule\s+)?10b5') AS negated
FROM filing_documents GROUP BY 1 ORDER BY 1;

SELECT substring(xml_text from '<[A-Za-z0-9_]*10b5[A-Za-z0-9_]*[^>]*>[^<]*</[A-Za-z0-9_]*10b5[A-Za-z0-9_]*>') AS element,
       COUNT(*) AS filings
FROM filing_documents WHERE filing_date >= '2023-04-01' AND xml_text ~* '10b5'
GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
