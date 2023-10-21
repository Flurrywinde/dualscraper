import os
import pandas as pd
import requests
import sys
import csv, re
from time import strftime, localtime, sleep
import fileinput
import waybackpy.exceptions
from lxml import etree as ET
from waybackpy import WaybackMachineCDXServerAPI
from itertools import islice
from collections import deque
from math import isnan
import sqlite3

# Settings
trywayback = True
sourcefiles = ['listing_part1.xml', 'listing_part2.xml']
accesstime = 0  # last time https://postcode.my was accessed
maxwait = 230  # delay / wait between accesses to postcode.my setting here. Was 222 and still got the catcha eventually (~1000?). 230 has consistently prevented the captcha for a while now.
retrydelay_incr = 10
waybackdelay = 1  # The Wayback Machine seems to throttle too, so I suggest not setting this to 0.
dbfile = './postcode.my/postcode-my.db'

def initdb(dbfile):
	try:
		conn = sqlite3.connect(dbfile)
	except:
		debugtee('debug', "Couldn't initialize database")
		sys.exit(1)
	conn.row_factory = sqlite3.Row
	return conn

def maketable(name, csvfile):
	# TODO: lat/long are text type; make real type. Had to manually do it in sqlitebrowser
	# Read in City.csv into Pandas dataframe
	df = pd.read_csv(csvfile, dtype=object)  # dtype=object keeps field an int as opposed to real
	#df = pd.read_csv(csvfile, dtype={'Latitude': float, 'Longitude': float})  # TypeError: Cannot cast array data from dtype('O') to dtype('float64') according to the rule 'safe' and ValueError: could not convert string to float: 'Latitude'
	#df = pd.read_csv(csvfile)  # turned postcode to int, so lost leading zero
	#print(df.dtypes, file=sys.stderr)  # verified lat long are floats if not dtype, but let's keep them strings, lest trailing zeroes removed
	# Turn dataframe into sqlite table
	df.to_sql(name, conn, if_exists='append', index=True)  # index=True creates auto-incrementing column named index

def dbexe_list(str, *parms):  # secure db execute (returns the cursor)
	# Use this to make fetchall return a list [a, b, c] instead of [(a,), (b,), (c,)] when select <one thing>
	cur = conn.cursor()
	cur.row_factory = lambda cursor, row: row[0]
	try:
		cur.execute(str, tuple(parms))
	except sqlite3.Error as er:
		debugtee('debug', 'Sql error:', er)
		debugtee('debug', f'Sql: {str} {parms}')
		sys.exit(1)
	return cur

def dbexe(str, *parms):  # secure db execute (returns the cursor)
	# rowid = insertdb("insert into blogs(name, site, autodl) values('?', '?', ?)",curblog, 'bdsmlr', autodl)
	try:
		cur = conn.cursor()
		cur.execute(str, tuple(parms))
	except sqlite3.Error as er:
		debugtee('debug', 'Sql error:', er)
		debugtee('debug', f'Sql: {str} {parms}')
		sys.exit(1)
	return cur

def getpages(xmlfiles):
	if isinstance(xmlfiles, str):
		xmlfiles = list(xmlfiles)
	elif not isinstance(xmlfiles, list):
		debugtee('debug', f'Error: getpages: string or list required but got {type(xmlfiles)}')
	count = 1
	for xfile in xmlfiles:
		tree = ET.parse(xfile)
		root = tree.getroot()  # root.tag, root.attrib
		ns = '{' + tree.getroot().tag[1:].split("}")[0] + '}'
		iterator = root.iterfind(f'.//{ns}loc')
		elements = deque(islice(iterator, 0, count))
		for element in iterator:
			elements.append(element)
			yield elements.popleft()
		yield from elements  # this gets the last one

def debugtee(dfile, text):
	debuglog(dfile, text)
	print("Debug: {0}".format(text))

def debuglog(dfile, text):
	with open("{0}.txt".format(dfile), "a+", encoding="utf-8") as text_file:
		text_file.write("{0}: {1}\n".format(strftime("%m-%d %H:%M:%S", localtime()), text))

def mkdir_p(path):
	try:
		os.makedirs(path)
	except OSError as exc:	# Python >2.5
		if exc.errno == errno.EEXIST and os.path.isdir(path):
			pass
		else:
			raise

# fixtable(): takes a dict (pandas table found in html). Returns True if all keys are in goodfields list, else False.
# Fixes case when table has adsbygoogle in field by removing that whole key/value pair. Everything else is correct. Oh, wait, that's a table unto itself, and the goodfields are in the next table. So this removes the bad field, leaving an empty table.
# {'Kawasan Industri Ringan Prima Kota, Kuantan (Postcode - 25200)  0 Stars.  (adsbygoogle = window.adsbygoogle || []).push({});  Listing Information  ItemDescription  LocationKawasan Industri Ringan Prima Kota  Post OfficeKuantan  StatePahang  Postcode25200  GPS Coordinate (Approximate)  Latitude : 3.8738240000  Longitude : 103.3312410000  Location, Maps and Direction': 'Add Review  Report Error  (adsbygoogle = window.adsbygoogle || []).push({});'}
# So, note: could get lat and long from the key in the dict above
def fixtable(t):
	goodfields = ['Location','Post Office','State','Postcode','Latitude','Longitude']
	badfield = False
	#debugtee('debug', f'fixtable: in2: {t}')
	for k in list(t):
		#debugtee('debug', f'fixtable: "--=={k}==--"', end='')
		if not k in goodfields:
			#debugtee('debug', f'Removing bad field: "{k}": "{t[k]}"')
			del t[k]
			badfield = True
			with open('badfields.txt', 'a') as f:
				f.write(str(t))
		#else:
			#debugtee('debug', 'good')
	if badfield:
		#debugtee('debug', f'fixtable: out: {t}')
		#debugtee('debug', f'fixtable: returning bad')
		return False
	else:
		#debugtee('debug', f'fixtable: out: {t}')
		#debugtee('debug', f'fixtable: returning good')
		return True

def getlatlong(row, html):
	# Could also get lat and long from the key in fixtable()
	keys = row.keys()
	if 'Latitude' in keys or 'Longitude' in keys:
		debugtee('debug', f'Should never happen. Found latlong in row: {row}')
		sys.exit(1)
	try:
		lat = re.search(r'Latitude( )*:.*?([-\.0123456789]+)', html)[2]
	except TypeError as e:
		# NoneType not subscriptable. No Latitude in html: https://web.archive.org/web/20160618121617/http://postcode.my/melaka-melaka-jabatan-perhubungan-perusahaan-75536.html
		debugtee('debug', f'No lat in html for row: {row}')
		with open('badlat.html', 'w') as f:
			f.write(html)
		return False
	except Exception as e:
		print("Unexpected error:", sys.exc_info()[0])
		debugtee('debug', f'doc: {e.__doc__}')
		debugtee('debug', e)
		raise

	try:
		long = re.search(r'Longitude( )*:.*?([-\.0123456789]+)', html)[2]
	except TypeError as e:
		debugtee('debug', f'No longitude in html for row: {row}')
		with open('badlong.html', 'w') as f:
			f.write(html)
		return False
	except Exception as e:
		print("Unexpected error:", sys.exc_info()[0])
		debugtee('debug', f'doc: {e.__doc__}')
		debugtee('debug', e)
		raise

	row['Latitude'] = lat
	row['Longitude'] = long
	return True

def livewait():
	global accesstime, accesstime_prev
	accesstime_prev = accesstime
	accesstime = time.time()
	sincelastaccess = accesstime - accesstime_prev
	sleepfor = maxwait - sincelastaccess  # delay / wait setting here
	if sleepfor > 0:
		if job == 'get2' or job == 'check4':
			print(f'Using postcode.my live data after sleeping for {sleepfor} seconds...', end='')
		else:
			print(f'Not on wayback machine, so use postcode.my live data after sleeping for {sleepfor} seconds...', end='')
		sleep(sleepfor)
		print('Done!')
	else:
		if job == 'get1':
			print('Not on wayback machine, so use postcode.my live data')

def getstartat():
	if os.path.isfile('startat.txt'):
		with open('startat.txt', 'r') as f:
			startat = int(f.read())
	else:
		with open('startat.txt', 'w') as f:
			f.write('0')
		startat = 0
	with open('laststartat.txt', 'w') as f:
		f.write(str(startat))
	return startat

def fixlatlong(url, row, bydeletion=False):
	if bydeletion:
		cur = dbexe(
			'select * from postcode where Location=? and "Post Office" = ? and State = ? and Postcode = ? and url = ? and Latitude != ? and Longitude != ?',
			row['Location'], row['Post Office'], row['State'], row['Postcode'], url, row['Latitude'],
			row['Longitude'])
		cur2 = dbexe(
			'delete from postcode where Location=? and "Post Office" = ? and State = ? and Postcode = ? and url = ? and Latitude != ? and Longitude != ?',
			row['Location'], row['Post Office'], row['State'], row['Postcode'], url, row['Latitude'], row['Longitude'])
	else:
		cur = dbexe(
			'select * from postcode where Location=? and "Post Office" = ? and State = ? and Postcode = ? and url = ?',
			row['Location'], row['Post Office'], row['State'], row['Postcode'], url)
		cur2 = dbexe(
			'update postcode set Latitude=?, Longitude=? where Location=? and "Post Office" = ? and State = ? and Postcode = ? and url = ?',
			row['Latitude'], row['Longitude'], row['Location'], row['Post Office'], row['State'], row['Postcode'], url)
	cur2.execute("select changes()")
	if cur2:
		changes = cur2.fetchall()[0][0]
		if changes != 1:
			debugtee('debug', f'Live (good) data: {row}')
			if bydeletion:
				actionstr = 'deleted'
			else:
				actionstr = 'changed'
			debugtee('debug', f'Warning: {actionstr} {changes} rows')
			for i in cur:
				debugtee('debug', list(i))
	else:
		debugtee('debug', f'bydel: {bydeletion}')
		debugtee('debug', f'fixlatlong: select changes() failed?!?')
		for i in cur:
			debugtee('debug', list(i))
		sys.exit(1)

def getwaybacksnapshots(url):
	snapshots = list(cdx.snapshots())
	# Should add try: here. Got: urllib3.exceptions.MaxRetryError and requests.exceptions.RetryError
	snapshots.reverse()
	return snapshots

def getwayurl():
	global advancesnap, waytry, wayurl, cursnap, year
	if advancesnap == False:
		# Connection error. Try again, keeping wayurl the same
		# TODO: maybe advance a counter here, so don't go forever
		advancesnap = True
	elif waytry == '' and wayurl == '':
		# tried everything, and still didn't work
		return None
	elif wayurl == '':
		# first time, use first snapshot
		try:
			waytry = snapshots[0]
		except IndexError:
			# But might not be any: https://postcode.my/kelantan-kuala-krai-taman-batu-lada-18000.html
			# waytry will still be 'start', so change to '', lest s.get try to get url with start prepended
			waytry = ''
	elif year < 0:
		# got all the way to the end, so go by cursnap
		cursnap += 1
		if cursnap < len(snapshots):
			waytry = snapshots[cursnap]
		else:
			# all out of snapshots, so go to real site
			waytry = ''
	else:
		# second time on, go by year
		try:
			waytry = cdx.near(year)
		except waybackpy.exceptions.NoCDXRecordFound as e:
			# happens when no snapshots for this url
			debugtee('debug', f'waytry near {year} not found')
			# waytry will still be 'start', so change to '', lest s.get try to get url with start prepended
			waytry = ''
		except Exception as e:
			debugtee('debug', 'waytry unknown error')
			debugtee('debug', e.__doc__)
			try:
				debugtee('debug', e.message)  # not all exceptions have this
			except AttributeError:
				# e has no attr message
				pass
			raise
	if hasattr(waytry, 'archive_url'):
		waytry = waytry.archive_url
	waytry = re.sub('http(s)?://postcode\.my.*', '', waytry)
	# if same as old, hit end, so go by cursnap now (but if wayurl == '', this means first time thru and waytry == '' means no snapshots)
	if waytry == wayurl and wayurl != '':
		year = -1
		cursnap += 1
		try:
			waytry = snapshots[cursnap]
		except IndexError:
			# happened when only 1 snapshot, and it was a captcha
			waytry = ''
		if hasattr(waytry, 'archive_url'):
			waytry = waytry.archive_url
		wayurl = re.sub('http(s)?://postcode\.my.*', '', waytry)
	else:
		# not same as old, so use it, i.e. didn't hit end, so proceed with previous year
		wayurl = waytry
	debugtee('debug', wayurl + url)
	return wayurl

def non200code(response):
	global year, advancesnap
	if response.status_code == 404:
		# Not found. Try again. (I think doesn't happen anymore. Was due to bad wayurl.)
		debugtee('debug', f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
		year -= 1
	elif response.status_code == 504:
		# Time out. Try again
		advancesnap = False
		debugtee('debug', f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
	elif response.status_code == 429:
		# Too many requests. Wait and try again
		advancesnap = False
		debugtee('debug', f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
		sleep(3)
	elif response.status_code == 500:
		# Internal server error. Wait and try again
		advancesnap = False
		debugtee('debug', f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
		sleep(3)
	elif response.status_code == 523:
		# Unknown error. Wait and try again
		advancesnap = False
		debugtee('debug', f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
		sleep(3)
	elif response.status_code == 520:
		# Unknown error. Wait and try again
		advancesnap = False
		debugtee('debug', f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
		sleep(3)
	elif response.status_code == 503:
		# Service unavailable. Wait and try again
		advancesnap = False
		debugtee('debug', f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
		sleep(3)
	elif response.status_code == 524:
		# No reason whatsoever??? Happened when catcha'd out and went to real postcode.my site. Wait and try again
		# Happened again, real postcode.my site, but not captcha
		advancesnap = False
		debugtee('debug', f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
		debugtee('debug', response)
		sleep(3)
	elif response.status_code == 502:
		# Bad gateway. Wait and try again
		advancesnap = False
		debugtee('debug', f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
		sleep(3)
	else:
		# Unknown failed request, so alert programmer to decide if needs sleep and/or advancesnap
		debugtee('debug', response.status_code)
		debugtee('debug', response.reason)
		debugtee('debug', response)
		sys.exit()

def procpage(response):
	global advanceurl
	try:
		tbls = pd.read_html(response.text)
	except ValueError as e:
		# Got no tables error. Was error on postcode.my at the time: https: // web.archive.org / web / 20131205013002 / http: // postcode.my / negeri - sembilan - kuala - klawang - taman - irama - 71600. html
		debugtee('debug', e)
		# log it to scrape manually
		with open('failed2.txt', 'a') as f:
			f.write(url + '\n')
		# save html for analysis
		with open('no_tables.html', 'w') as f:
			f.write(response.text)
		# continue with next url
		return None
	row = {}
	tcount = 0
	for t in tbls:
		# each t is a pandas dataframe
		tcount += 1
		try:
			t = dict(t.values)  # convert from Item, Description to "proper" dict (i.e. Location, ... , Longitude)
		except ValueError as e:
			# fails for the bad table (adsbygoogle) cuz seems need only 2 each (one for key, one for value), but there's 4
			# ah, it's the search form, so just skip
			#with open('adsby.txt', 'w') as f:
			#	f.write(str(t))
			#with open('adsby_info.txt', 'w') as f:
			#	f.write(t.info())
			#with open('adsby_values.txt', 'w') as f:
			#	f.write(str(t.values))
			#	t = t.values
			#sys.exit()
			return None
		# Throw out bad keys like adsbygoogle. Keep only good ones like Location, State, etc
		fixtable(t)
		# Add data in t to collection in row
		try:
			#row.update(t.values)
			row.update(t)
		except ValueError as e:
			debugtee('debug', e)
			debugtee('debug', 'I think this was for when was t.values, so will not happen now')
			sys.exit()
			# dictionary update sequence element  # 0 has length 4; 2 is required
			# Bad: 0... 3 0
			# Find: ... NaN 1
			# NaN...NaN 2
			# Keyword...NaN
			# [3 rows x 4 columns]
			#
			# This is the search form, so just skip it
			debugtee('debug', f'Bad: {t}')
			fname = re.sub('/', '+', f'{wayurl}{url}-{tcount}')
			# Log the table for debugging (can del if always just the search form)
			with open(f'{fname}.tbl', 'w') as f:
				f.write(str(t))
			# Log the html to parse manually later
			with open(f'{fname}.html', 'w') as f:  # added the '2'. Means skip cuz hopefully getting latlong now
				f.write(response.text)
			return None
	# check if still need to get latlong
	if 'Latitude' not in row.keys():  # only Lat good enough?
		if getlatlong(row, response.text):
			debugtee('debug', f'NEW LATLONG {c}:\t{row}')
			with open('newlatlong.txt', 'a') as f:
				f.write(str(row) + '\n')
		else:
			# Still failed to get lat long
			debugtee('debug', 'still no latlong')
			advanceurl = False
			return None

	# latlong is 0.0000: https://web.archive.org/web/20140724100239/http://postcode.my/melaka-melaka-jabatan-anti-malaria-75584.html
	try:
		if float(row['Latitude']) == 0 and float(row['Longitude']) == 0:
			debugtee('debug', f'latlong zeroes:\t{row}')
			advanceurl = False
			return None
	except KeyError:
		# lat or long not even in row
		advanceurl = False
		return None

	# latlong might be empty: https://web.archive.org/web/20150619125202/http://postcode.my/melaka-melaka-jabatan-perangkaan-75514.html
	# debugtee('debug', f'bad latlong: {row}')
	if isinstance(row['Latitude'], float):  # need check long too?
		if isnan(row['Latitude']):
			debugtee('debug', f'blank latlong: {row}')
			advanceurl = False
			return None
	return row

########
# MAIN #
########

# Initialization Section
if not trywayback:
	# Make directory (if it doesn't exist already) for postcode.my .db and .csv file
	mkdir_p('postcode.my')
	# Connect the database for non-wayback mode
	conn = initdb(dbfile)
# Set up requests session and output csv file
s = requests.Session()
outfile = open('output.csv', 'w')
w = csv.writer(outfile)

# Get list of urls to scrape
urls = getpages(sourcefiles)

# Set startat (used by main loop to skip already dones)
# TODO: handle case where want to re-run with same startat. Only if run `./harvest` will new figures be respected. For now, do manually with: `harvest reset`.
startat = getstartat()  # Also, sets up files used to pick up where left off (startat.txt and laststartat.txt)

# Main loop
c = 0
success = True
while True:
	if success:
		# Get next url if prev was successful (or on very first url), otherwise keep it the same to try again
		try:
			url = next(urls)
		except StopIteration:
			break
		# f.write(f'{url.text}\n')  # this was to verify getpages() correctness with grep-made urls
		if c < startat:
			debugtee('debug', f'{c}: Skipping: {url.text}')
			c += 1
			continue
		# Reset retrydelay if prev was successful, otherwise let it increment to wait longer and longer each time
		retrydelay = 0
	if hasattr(url, 'text'):  # won't if not advancing url, and url already ok
		url = url.text
	if trywayback:
		# Setup snapshots loop initial conditions
		if success:  # Will always be true first time thru loop
			cdx = WaybackMachineCDXServerAPI(url)
			# url has changed so get snapshots for new url
			snapshots = getwaybacksnapshots(url)
			# only start the snaps over if url advanced, otherwise, go on with next snapshot
			cursnap = 0
			year = 2023
			wayurl = ''
			waytry = 'start'
			advancesnap = True
	# Set success to False by default, so only if actually succeed further on will it be True
	success = False
	# Loop through all snapshots (or just live site if trywayback is false)
	while True:
		if trywayback:
			wayurl = getwayurl()  # Sets globals, you bad programmer
			if wayurl is None:
				debugtee('debug', "Hmmm... won't break cause it to not try live site? Change this to just set wayurl to ''?")
				break
		else:
			wayurl = ''

		# Avoid getting throttled/captcha'ed
		if wayurl == '':
			# Wait if going live
			livewait()
		elif c > 0 and trywayback:
			# Shorter wait for wayback machine
			sleep(waybackdelay)
		# Get the page
		try:
			response = s.get(wayurl + url)
		except requests.exceptions.ConnectionError as e:
			debugtee('debug', e)
			if retrydelay > 0:
				print(f'Waiting {retrydelay} seconds before retrying... ', end='')
				sleep(retrydelay)
				print('Done!')
			retrydelay += retrydelay_incr
			if trywayback:
				advancesnap = False
				debugtee('debug', f'about to continue. wt: {waytry}, wu: {wayurl}')
			continue
		except Exception as e:
			debugtee('debug', f'Unknown Error in s.get call: {e.__doc__}')
			try:
				debugtee('debug', e.message)  # not all exceptions have this
			except AttributeError:
				# e has no attr message
				pass
			debugtee('debug', '-----')
			debugtee('debug', e)
			debugtee('debug', '-----')
			raise

		# Process response
		if response.status_code == 200:
			# request successful
			if re.search(r'Unusual Traffic Activity', response.text):
				if trywayback:
					# but got captcha, so try again with older snapshot
					debugtee('debug', f'{c}: Captcha: {wayurl + url}')
					year -= 1
					continue
				else:
					# Live site captcha
					print('reset captcha please')
					os.system('dunstify Postcode "Reset captcha!"')
					sys.exit()
			else:
				# Got the html. This will end this inner loop.
				success = True
				break
		else:
			# request unsuccessful (loop will continue)
			non200code(response)
	# End of snapshot loop

	# Assume success if got here
	if not success:
		debugtee('debug', "Hey! Don't come here if not successful.")
		sys.exit(1)
	# Extract lat/long data from page. Assume success if got here
	row = procpage(response)
	if row is not None:
		# Successfully found scrape data. Show what we found on stdout
		debugtee('debug', f'{c}: {row}')
		if trywayback:
			# Write csv header if needed
			if c == 0:
				w.writerow(row.keys())
			# Write the row to the output file
			w.writerow(row.values())
		else:
			# non-wayback mode. Update database.
			cur = dbexe('select * from postcode where Location=? and "Post Office"=? and State=? and Postcode=?', row['Location'], row['Post Office'], row['State'], row['Postcode'])
			csvrows = cur.fetchall()  # csv is misnomer now; change to db
			if len(csvrows) == 0:
				# Should never happen. No csv data found. Log it
				print(f"No csv data found for loc: {row['Location']}, po: {row['Post Office']}, st: {row['State']}, postcode: {row['Postcode']}")
				sys.exit(1)
			goodc = 0
			badc = 0
			#badlatlongs = []
			for csvrow in csvrows:
				#print(f"{type(csvrow['Latitude'])} {type(row['Latitude'])} {type(csvrow['Longitude'])} == type(row['Longitude']):
				#print(type(csvrow['Latitude']), type(row['Latitude']), type(csvrow['Longitude']), type(row['Longitude']))  # csvrow latlong is float type. Manually changed db
				#if csvrow['Latitude'] == row['Latitude'] and csvrow['Longitude'] == row['Longitude']:
				if csvrow['Latitude'] is None:  # long too?
					badc += 1
				elif float(csvrow['Latitude']) == float(row['Latitude']) and float(csvrow['Longitude']) == float(row['Longitude']):
					# Good
					goodc += 1
					goodw.writerow(dict(csvrow).values())
					good_fh.flush()
				else:
					badc += 1
					#badlatlongs.append({'Latitude': csvrow['Latitude'], 'Longitude': csvrow['Longitude']})
					badw.writerow(dict(csvrow).values())
					bad_fh.flush()
					# Report if lat or long different
					print(f"Lat/long different - live vs csv:\n\t{row['Latitude']},\t{row['Longitude']}\n\t{csvrow['Latitude']},\t{csvrow['Longitude']}")
			if goodc > 0 and badc > 0:
				print(f'Good row also found (count: {goodc}), so fixing db by deleting bad row(s)')
				if goodc > 1:
					print(f'Warning: more than one good row in db. (Ok if url is different, though still consider removing. Check good.csv .')
			if goodc == 0 and badc > 0:
				# Change bad to good in db
				fixlatlong(url, row)
				conn.commit()
			elif goodc > 0 and badc > 0:
				fixlatlong(url, row, bydeletion=True)
				conn.commit()

		# Advance the counter
		c += 1
		# Save c to pick up where left off next run
		with open('startat.txt', 'w') as f:
			f.write(str(c))

# End of main loop
print('All done!')
# Make the database
if trywayback:
	mkdir_p('postcode.my')
	initdb(dbfile)
	maketable('postcode', 'allsofar.csv')
	dbexe("alter table postcode add column url;")
	dbexe('CREATE INDEX idx_postcode_url ON postcode(url);')
	conn.commit()
