# dualscraper
Scrapes lat/long data from postcode.my, trying the Wayback Machine first, due to CloudFlare throttling.

The purpose of this repo is to serve as a template and demonstration of an MVP for scraping sites that employ CloudFlare throttling (presenting a Captcha if scraped too fast). To speed up the process, it tries the Wayback Machine first, only falling back to the live site if the page in question isn't on the Wayback Machine (or the data, in this case lat/long data, isn't there or looks definitely wrong).

## The lat/long data
Currently, I have scraped all the urls, but I'm sure a lot of the lat/long data is still old and different from the current data. The coordinates seem nearby, though, so perhaps they will still be of use before all data is current. (Estimated time: a few more weeks.)

### .csv file
[https://github.com/Flurrywinde/dualscraper/raw/main/postcode.my/postcode-my.csv](https://github.com/Flurrywinde/dualscraper/raw/main/postcode.my/postcode-my.csv)

### sqlite database
[https://github.com/Flurrywinde/dualscraper/raw/main/postcode.my/postcode-my.db](https://github.com/Flurrywinde/dualscraper/raw/main/postcode.my/postcode-my.db)

(also has a column containing the url)

## Installation
```
$ mkdir /path/to/project
$ cd /path/to/project
$ git clone git@github.com:Flurrywinde/dualscraper.git .
$ wget 'https://postcode.my/xml/listing_part1.xml.gz'
$ wget 'https://postcode.my/xml/listing_part2.xml.gz'
$ gunzip listing_part1.xml.gz
$ gunzip listing_part2.xml.gz
```

## Usage
### Initial run
```
$ cd /path/to/project
$ python dualscraper.py
```
Initial output is to `output.csv`. (Erased each run. See below.)

Since this will scrape more than 50,000 webpages with significant delays between them, this could take a long time. You can hit ctrl-c to abort at any time without losing data. (See below.)

### Pick up where left off
The script can be stopped and restarted, picking up where it left off if the utility `harvest` is run in-between.

`harvest` appends `output.csv` to `allsofar.csv`. (It also copies it to a file like `0-11.csv` containing only the current run's harvest.)

(Internally, the files `startat.txt` and `laststartat.txt` are used to track where you are. Don't mess with them unless you know what you are doing.)

### Slow Non-Wayback Machine Mode
Since a site might've updated since being crawled by the Wayback Machine, once all data (from the site's sitemap .xml files) is obtained, use non-wayback mode to slowly re-scrape only the live site.

At the top of dualscraper.py, change `trywayback` to False to only scrape from the live site. (TODO: add command line parameters for things like this. Also, a config file.)

Running in non-wayback mode will create a sqlite database (located in `./postcode.my`, which will be created if necessary) with all data in `allsofar.csv`. All updates from the re-scraping affect this database only (but a .csv file can be created from it. See below.).

### Output a .csv file from the sql data
To output a sorted .csv file from the current database, run `db2csv`. This .csv file will be in `./postcode.my` under the filename `postcode-my.csv`.

## TODO
* Use `pipreqs` to make a requirements.txt file and add a Dependencies section to this readme.
	* Note: `dunst` is an optional dependency to alert user when the captcha happens.

## Errors found on the postcode.my site
### Wrong urls
| Url                                                                                          | Error                    |
| -------------------------------------------------------------------------------------------- | ------------------------ |
| https://postcode.my/perak-bandar-seri-iskandar-uitm-cawangan-bandar-seri-iskandar-32600.html | Postcode should be 32610 |
| https://postcode.my/selangor-subang-jaya-subang-jaya-usj-9-11-47610.html                     | Postcode should be 47620 |

There're also a few urls missing a hyphen. I found them because, during development, part of checking the data was constructing the url from the Location, Post Office, State, and Postcode. A few times, this url differed from the ones in postcode.my's sitemap files, but I didn't write them down.

### Changes over time
* Current site as of 10/25/23 has this data: {'Location': 'Jalan Bakri Batu 2', 'Post Office': 'Muar', 'State': 'Johor', 'Postcode': '84000', 'Latitude': 2.048207, 'Longitude': 102.5775359}, but on Wayback Machine, Location was: 'Jalan Bakri (Batu 2)' See: https://web.archive.org/web/20140730113802/http://postcode.my/johor-muar-jalan-bakri-batu-2-84000.html
* Current site as of 10/25/23 has this data: {'Location': 'Kampung Baru Bakri', 'Post Office': 'Muar', 'State': 'Johor', 'Postcode': '84200', 'Latitude': 2.0411917, 'Longitude': 102.646845}, but on Wayback Machine, Location was: 'Kampung Baru (Bakri)'
* Current site as of 11/01/23 has this data: {'Location': 'Kampung Lobak', 'Post Office': 'Karangan', 'State': 'Kedah', 'Postcode': '09700', 'Latitude': 5.5035641, 'Longitude': 100.6284483}, but on Wayback Machine, Location was: 'Kampung LOBAK'
* Current site as of 11/06/23 has this data: {'Location': 'Hospital Usm', 'Post Office': 'Kota Bharu', 'State': 'Kelantan', 'Postcode': '15990', 'Latitude': 6.0990447, 'Longitude': 102.2808537}, but on Wayback Machine, Location was: 'Hospital USM'
* Current site as of 11/08/23 has this data: {'Location': "Cucuh Puteri 'B'", 'Post Office': 'Kuala Krai', 'State': 'Kelantan', 'Postcode': '18000', 'Latitude': 5.3512758, 'Longitude': 102.3193938}, but on Wayback Machine, Location was:  "Cucuh Puteri `B'"
* Current site as of 11/17/23 has this data: {'Location': "Kampung Tengah Melaka Pindah", 'Post Office': 'Alor Gajah', 'State': 'Melaka', 'Postcode': '78000', 'Latitude': 2.4077702, 'Longitude': 102.1777214}, but on Wayback Machine, Location was:   "Kampung Tengah (Melaka Pindah)"
* Current site as of 11/18/23 has this data: {'Location': "Kampung Tebat", 'Post Office': 'Alor Gajah', 'State': 'Melaka', 'Postcode': '78000', 'Latitude': 2.373973, 'Longitude': 102.2114239}, but on Wayback Machine, Location was:  "Kampung (Tebat)"
* Current site as of 11/20/23 has this data: {'Location': 'Jasin Industrial Park', 'Post Office': 'Bemban', 'State': 'Melaka', 'Postcode': '77200', 'Latitude': 2.2873868, 'Longitude': 102.408433}, but on Wayback Machine, Location was:  "Jasin IndustRial Park"
* Current site as of 11/22/23 has this data: {'Location': 'Kampung Tengah Berisu', 'Post Office': 'Lubok China', 'State': 'Melaka', 'Postcode': '78100', 'Latitude': 2.435383, 'Longitude': 102.1317059}, but on Wayback Machine, Location was:  "Kampung Tengah (Berisu)"
* Current site as of 11/25/23 has this data: {'Location': 'Kampung Tengah Tanjong Minyak', 'Post Office': 'Melaka', 'State': 'Melaka', 'Postcode': '75260', 'Latitude': 2.224285, 'Longitude': 102.2021632}, but on Wayback Machine, Location was:  "Kampung Tengah (Tanjong Minyak)"
* Current site as of 11/30/23 has this data: {'Location': 'Bandar Baru Enstek', 'Post Office': 'Bandar Enstek', 'State': 'Negeri Sembilan', 'Postcode': '71760', 'Latitude': 2.741725, 'Longitude': 101.762897}, but on Wayback Machine, Location was:  "Bandar Baru ENSTEK"

### Duplicate urls
I combined listing_part1.xml and listing_part2.xml and discovered these urls were in the combined listing twice:

https://postcode.my/johor-muar-jalan-bakri-batu-2-84000.html  
https://postcode.my/johor-muar-kampung-baru-bakri-84200.html  
https://postcode.my/johor-pontian-kampung-pesisir-82000.html  
https://postcode.my/johor-segamat-jalan-merbok-85000.html  
https://postcode.my/johor-segamat-kampung-paya-besar-85000.html  
https://postcode.my/johor-senai-taman-impian-jaya-senai-81400.html  
https://postcode.my/johor-simpang-rengam-taman-damai-86200.html  
https://postcode.my/kelantan-kota-bharu-kampung-belukar-salor-15100.html  
https://postcode.my/melaka-ayer-keroh-k-ekonomi-75450.html  
https://postcode.my/melaka-melaka-kompleks-perniagaan-al-azim-75400.html  
https://postcode.my/perak-jeram-kampung-baru-kuala-dipang-31850.html  
https://postcode.my/perak-rantau-panjang-kampung-tengah-ulu-mengkuang-34140.html  
https://postcode.my/perak-ulu-kinta-kampung-tersusun-batu-6-8-1-4-31150.html  
https://postcode.my/pulau-pinang-balik-pulau-pantai-acheh-mk-1-11010.html  
https://postcode.my/pulau-pinang-pulau-pinang-jalan-kampung-jawa-baru-10150.html  
https://postcode.my/pulau-pinang-pulau-pinang-jalan-kampung-jawa-lama-10150.html  
https://postcode.my/sabah-kota-kinabalu-lorong-bunga-dedap-1-2-88300.html  
https://postcode.my/sarawak-kuching-kampung-tematu-jalan-batu-kitang-93250.html  
https://postcode.my/sarawak-kuching-taman-height-estate-jalan-stutong-93350.html  
https://postcode.my/selangor-klang-jalan-dahlia-ku-8-41050.html  
https://postcode.my/selangor-petaling-jaya-jalan-jenjarum-pju-6a-47400.html  
https://postcode.my/wilayah-persekutuan-kuala-lumpur-jalan-taman-u-thant-55000.html  
https://postcode.my/wilayah-persekutuan-putrajaya-jalan-merbau-p14d-1-jalan-p14d-1-62050.html  
https://postcode.my/wilayah-persekutuan-putrajaya-jalan-merbau-p14d-2-jalan-p14d-2-62050.html  
