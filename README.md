# dualscraper
Scrapes lat/long data from postcode.my, trying the Wayback Machine first, due to CloudFlare throttling.

The purpose of this repo is to serve as a template and demonstration of an MVP for scraping sites that employ CloudFlare throttling (presenting a Captcha if scraped too fast). To speed up the process, it tries the Wayback Machine first, only falling back to the live site if the page in question isn't on the Wayback Machine (or the data, in this case lat/long data isn't there).

## Usage
```
# cd /path/to/project  # `mkdir` this first if necessary
# cd /path/to/project  # `mkdir` this first if necessary
# wget 'https://postcode.my/xml/listing_part1.xml.gz'
# wget 'https://postcode.my/xml/listing_part2.xml.gz'
# gunzip listing_part1.xml.gz
# gunzip listing_part2.xml.gz
# python dualscraper.py
```
Initial output is to `output.csv`. (Erased each run. See below.)

### Pick up where left off
The script can be stopped and restarted, picking up where it left off if the utility `harvest` is run in-between.

`harvest` appends `output.csv` to `allsofar.csv`. (It also copies it to a file like `0-11.csv` containing only the current run's harvest.)

(Internally, the files `startat.txt` and `laststartat.txt` are used to track where you are. Don't mess with them unless you know what you are doing.)

### Slow Non-Wayback Machine Mode
Since a site might've updated since being crawled by the Wayback Machine, once all data (from the site's sitemap .xml files) is obtained, use non-wayback mode to slowly re-scrape only the live site.

At the top of dualscraper.py, change `trywayback` to False to only scrape from the live site. (TODO: add command line parameters for things like this. Also, a config file.)

Running in non-wayback mode will create a sqlite database with all data in `allsofar.csv`.

### Output a .csv file from the sql data
To output a sorted .csv file from the current database, run `db2csv`.

## TODO
* Use `pipreqs` to make a requirements.txt file and add a Dependencies section to this readme.
	* Note: `dunst` is an optional dependency to alert user when the captcha happens.
