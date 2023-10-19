# dualscraper
Scrapes lat/long data from postcode.my, trying the Wayback Machine first, due to CloudFlare throttling.

The purpose of this repo is to serve as a template and demonstration of an MVP for scraping sites that employ CloudFlare throttling (presenting a Captcha if scraped too fast). To speed up the process, it tries the Wayback Machine first, only falling back to trying the live site if the page in question isn't on the Wayback Machine.

Since a site might've updated since being crawled by the Wayback Machine, once all data (from the site's sitemap .xml files) is obtained, it will begin slowly scraping only the live site to retain only the latest information.

Initial output is to a .csv file which is later converted to SQLite.

The script can be stopped and restarted, picking up where it left off if the utility `harvest` is run in-between.

To output a sorted .csv file from the current database, run `db2csv`.

## Usage
\# cd /path/to/project  # `mkdir` this first if necessary
\# cd /path/to/project  # `mkdir` this first if necessary
\# wget 'https://postcode.my/xml/listing_part1.xml.gz'
\# wget 'https://postcode.my/xml/listing_part2.xml.gz'
\# gunzip listing_part1.xml.gz
\# gunzip listing_part2.xml.gz
\# python dualscraper.py
