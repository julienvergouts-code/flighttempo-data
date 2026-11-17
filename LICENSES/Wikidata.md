# Wikidata structured data

Provider: Wikidata / Wikimedia Foundation  
Source: https://www.wikidata.org/  
Query endpoint: https://query.wikidata.org/sparql  
Licence: CC0-1.0 / public domain for structured data.

Policy: https://www.wikidata.org/wiki/Wikidata:Licensing

Wikidata states that structured data in its main, Property, Lexeme and EntitySchema namespaces is released under Creative Commons Zero. Text in other namespaces and media hosted on Wikimedia Commons can have different licences; this pipeline consumes structured entity properties and labels only, and does not download images or article text.

The Query Service is a public endpoint. The workflow uses a descriptive User-Agent, performs one bounded query per scheduled run, retries transient errors, and does not fan out per airline.

This directory is descriptive reference data only. It is not a current operating certificate register, timetable, schedule, or operational aviation source.
