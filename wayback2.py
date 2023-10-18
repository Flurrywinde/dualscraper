import os
import pandas as pd
import requests
import sys
import csv, re, time
import fileinput
import waybackpy.exceptions
from lxml import etree as ET
from waybackpy import WaybackMachineCDXServerAPI
from itertools import islice
from collections import deque
from math import isnan
import sqlite3

sourcefiles = ['listing_part1.xml', 'listing_part2.xml']
accesstime = 0  # last time https://postcode.my was accessed
maxwait = 230  # delay / wait between accesses to postcode.my setting here. Was 222 and still got the catcha eventually (~1000?)
retrydelay_incr = 10
dbfile = './postcode.my/postcode-my.db'

def initdb(dbfile):
	try:
		conn = sqlite3.connect(dbfile)
	except:
		print("Couldn't initialize database")
		sys.exit(1)
	conn.row_factory = sqlite3.Row
	return conn

def dbexe_list(str, *parms):  # secure db execute (returns the cursor)
	# Use this to make fetchall return a list [a, b, c] instead of [(a,), (b,), (c,)] when select <one thing>
	cur = conn.cursor()
	cur.row_factory = lambda cursor, row: row[0]
	try:
		cur.execute(str, tuple(parms))
	except sqlite3.Error as er:
		print('Sql error:', er)
		print(f'Sql: {str} {parms}')
		sys.exit(1)
	return cur

def dbexe(str, *parms):  # secure db execute (returns the cursor)
	# rowid = insertdb("insert into blogs(name, site, autodl) values('?', '?', ?)",curblog, 'bdsmlr', autodl)
	try:
		cur = conn.cursor()
		cur.execute(str, tuple(parms))
	except sqlite3.Error as er:
		print('Sql error:', er)
		print(f'Sql: {str} {parms}')
		sys.exit(1)
	return cur

def getpages(xmlfiles):
	if isinstance(xmlfiles, str):
		xmlfiles = list(xmlfiles)
	elif not isinstance(xmlfiles, list):
		print(f'Error: getpages: string or list required but got {type(xmlfiles)}')
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

# fixtable(): takes a dict (pandas table found in html). Returns True if all keys are in goodfields list, else False.
# Fixes case when table has adsbygoogle in field by removing that whole key/value pair. Everything else is correct. Oh, wait, that's a table unto itself, and the goodfields are in the next table. So this removes the bad field, leaving an empty table.
# {'Kawasan Industri Ringan Prima Kota, Kuantan (Postcode - 25200)  0 Stars.  (adsbygoogle = window.adsbygoogle || []).push({});  Listing Information  ItemDescription  LocationKawasan Industri Ringan Prima Kota  Post OfficeKuantan  StatePahang  Postcode25200  GPS Coordinate (Approximate)  Latitude : 3.8738240000  Longitude : 103.3312410000  Location, Maps and Direction': 'Add Review  Report Error  (adsbygoogle = window.adsbygoogle || []).push({});'}
# So, note: could get lat and long from the key in the dict above
def fixtable(t):
	goodfields = ['Location','Post Office','State','Postcode','Latitude','Longitude']
	badfield = False
	#print(f'fixtable: in2: {t}')
	for k in list(t):
		#print(f'fixtable: "--=={k}==--"', end='')
		if not k in goodfields:
			#print(f'Removing bad field: "{k}": "{t[k]}"')
			del t[k]
			badfield = True
			with open('badfields.txt', 'a') as f:
				f.write(str(t))
		#else:
			#print('good')
	if badfield:
		#print(f'fixtable: out: {t}')
		#print(f'fixtable: returning bad')
		return False
	else:
		#print(f'fixtable: out: {t}')
		#print(f'fixtable: returning good')
		return True

def getlatlong(row, html):
	# Could also get lat and long from the key in fixtable()
	keys = row.keys()
	if 'Latitude' in keys or 'Longitude' in keys:
		print(f'Should never happen. Found latlong in row: {row}')
		sys.exit(1)
	try:
		lat = re.search(r'Latitude( )*:.*?([-\.0123456789]+)', html)[2]
	except TypeError as e:
		# NoneType not subscriptable. No Latitude in html: https://web.archive.org/web/20160618121617/http://postcode.my/melaka-melaka-jabatan-perhubungan-perusahaan-75536.html
		print(f'No lat in html for row: {row}')
		with open('badlat.html', 'w') as f:
			f.write(html)
		return False
	except Exception as e:
		print("Unexpected error:", sys.exc_info()[0])
		print(f'doc: {e.__doc__}')
		print(e)
		raise

	try:
		long = re.search(r'Longitude( )*:.*?([-\.0123456789]+)', html)[2]
	except TypeError as e:
		print(f'No longitude in html for row: {row}')
		with open('badlong.html', 'w') as f:
			f.write(html)
		return False
	except Exception as e:
		print("Unexpected error:", sys.exc_info()[0])
		print(f'doc: {e.__doc__}')
		print(e)
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
		time.sleep(sleepfor)
		print('Done!')
	else:
		if job == 'get1':
			print('Not on wayback machine, so use postcode.my live data')

def getstartat():
	# TODO: handle case where want to re-run with same startat. Only if run `./harvest` will new figures be respected
	with open('startat.txt', 'r') as f:  # Initially do: `echo 0 > startat.txt`
		startat = int(f.read())
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
			print(f'Live (good) data: {row}')
			if bydeletion:
				actionstr = 'deleted'
			else:
				actionstr = 'changed'
			print(f'Warning: {actionstr} {changes} rows')
			for i in cur:
				print(list(i))
	else:
		print(f'bydel: {bydeletion}')
		print(f'fixlatlong: select changes() failed?!?')
		for i in cur:
			print(list(i))
		sys.exit(1)

########
# MAIN #
########

trywayback = False

trywayback = True
# Set up requests session and output csv file
s = requests.Session()
outfile = open('output.csv', 'w')
w = csv.writer(outfile)
# Get list of urls to scrape
# urls = getpages(sourcefiles)
urls = getpages_old()

# Only get1 and get2 get here
# Manually skip past what already did
# TODO: handle case where want to re-run with same startat. Only if run `./harvest` will new figures be respected
#startat = 11698
with open('startat.txt', 'r') as f:  # Initially do: `echo 0 > startat.txt`
	startat = int(f.read())
with open('laststartat.txt', 'w') as f:
	f.write(str(startat))

# Skip already dones
c = 0
while c < startat:
	if job == 'get1':
		url = urls.pop().text
		#url = next(urls).text
	else:
		# get2
		url = next(urls)
	print(f'{c}: Skipping: {url}')
	c += 1

# Only get1 gets here
# Loop through all urls
advanceurl = True  # normal case. If False, stick with old url (currently happens if url fetched successfully, but no latlong on page)
while True:
	if advanceurl:
		try:
			url = urls.pop()
		except IndexError:
			break
		#try:
		#	url = next(urls)
		#except StopIteration:
		#	break

	if hasattr(url, 'text'):  # won't if not advancing url, and url already ok
		url = url.text

	#user_agent = "Mozilla/5.0 (Windows NT 5.1; rv:40.0) Gecko/20100101 Firefox/40.0"
	#cdx = WaybackMachineCDXServerAPI(site, user_agent)
	cdx = WaybackMachineCDXServerAPI(url)
	#print('Getting snapshot urls... ', end='')
	snapshots = list(cdx.snapshots())
	# Should add try: here. Got: urllib3.exceptions.MaxRetryError and requests.exceptions.RetryError
	snapshots.reverse()
	#numsnaps = len(snapshots)  # delme, done below now
	#if numsnaps == 0:
	#	livewait()
	# Loop through all snapshots
	success = False
	if advanceurl:
		# only start the snaps over if url advanced, otherwise, go on with next snapshot
		cursnap = 0
		year = 2023
		wayurl = ''
		waytry = 'start'
	advancesnap = True
	advanceurl = True
	while True:
		if advancesnap == False:
			# Connection error. Try again, keeping wayurl the same
			# TODO: maybe advance a counter here, so don't go forever
			advancesnap = True
		elif waytry == '' and wayurl == '':
			# tried everything, and still didn't work
			break
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
				print(f'waytry near {year} not found')
				# waytry will still be 'start', so change to '', lest s.get try to get url with start prepended
				waytry = ''
			except Exception as e:
				print('waytry unknown error')
				print(e.__doc__)
				try:
					print(e.message)  # not all exceptions have this
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
		print(wayurl + url)

		# Wait if going live
		if wayurl == '':
			livewait()
		# Get the page
		try:
			response = s.get(wayurl + url)
		except requests.exceptions.ConnectionError as e:
			print(f'Connection Error in s.get call: {e.__doc__}')  # A Connection error occurred
			try:
				print(e.message)  # not all exceptions have this
			except AttributeError:
				# e has no attr message
				pass
			print('-----')
			print(e)  # ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
			print('-----')
			advancesnap = False
			print(f'about to continue. wt: {waytry}, wu: {wayurl}')
			continue
		except Exception as e:
			print(f'Unknown Error in s.get call: {e.__doc__}')
			try:
				print(e.message)  # not all exceptions have this
			except AttributeError:
				# e has no attr message
				pass
			print('-----')
			print(e)
			print('-----')
			advancesnap = False
			#continue
			raise

		# Process response
		if response.status_code == 200:
			# request successful
			if re.search(r'Unusual Traffic Activity', response.text):
				# but got captcha, so try again with older snapshot
				print(f'{c}: Captcha: {wayurl + url}')
				year -= 1
			else:
				# Got the html. This will end this inner loop.
				success = True
				break
		else:
			# request unsuccessful
			if response.status_code == 404:
				# Not found. Try again. (I think doesn't happen anymore. Was due to bad wayurl.)
				print(f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
				year -= 1
			elif response.status_code == 504:
				# Time out. Try again
				advancesnap = False
				print(f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
			elif response.status_code == 429:
				# Too many requests. Wait and try again
				advancesnap = False
				print(f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
				time.sleep(3)
			elif response.status_code == 500:
				# Internal server error. Wait and try again
				advancesnap = False
				print(f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
				time.sleep(3)
			elif response.status_code == 523:
				# Unknown error. Wait and try again
				advancesnap = False
				print(f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
				time.sleep(3)
			elif response.status_code == 520:
				# Unknown error. Wait and try again
				advancesnap = False
				print(f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
				time.sleep(3)
			elif response.status_code == 503:
				# Service unavailable. Wait and try again
				advancesnap = False
				print(f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
				time.sleep(3)

			elif response.status_code == 524:
				# No reason whatsoever??? Happened when catcha'd out and went to real postcode.my site. Wait and try again
				# Happened again, real postcode.my site, but not captcha
				advancesnap = False
				print(f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
				print(response)
				time.sleep(3)
			elif response.status_code == 502:
				# Bad gateway. Wait and try again
				advancesnap = False
				print(f'{c}: {response.status_code} {response.reason}: {wayurl}{url}')
				time.sleep(3)
			else:
				# Unknown failed request, so alert programmer
				print(response.status_code)
				print(response.reason)
				print(response)
				sys.exit()

	# We tried to get the webpage and may or may not have succeeded
	if success:
		# Assume success and try to get the tables
		try:
			tbls = pd.read_html(response.text)
		except ValueError as e:
			# Got no tables error. Was error on postcode.my at the time: https: // web.archive.org / web / 20131205013002 / http: // postcode.my / negeri - sembilan - kuala - klawang - taman - irama - 71600. html
			print(e)
			# log it to scrape manually
			with open('failed2.txt', 'a') as f:
				f.write(url + '\n')
			# save html for analysis
			with open('no_tables.html', 'w') as f:
				f.write(response.text)
			# continue with next url
			continue
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
				continue
			# Throw out bad keys like adsbygoogle. Keep only good ones like Location, State, etc
			fixtable(t)
			# Add data in t to collection in row
			try:
				#row.update(t.values)
				row.update(t)
			except ValueError as e:
				print(e)
				print('I think this was for when was t.values, so will not happen now')
				sys.exit()
				# dictionary update sequence element  # 0 has length 4; 2 is required
				# Bad: 0... 3 0
				# Find: ... NaN 1
				# NaN...NaN 2
				# Keyword...NaN
				# [3 rows x 4 columns]
				#
				# This is the search form, so just skip it
				print(f'Bad: {t}')
				fname = re.sub('/', '+', f'{wayurl}{url}-{tcount}')
				# Log the table for debugging (can del if always just the search form)
				with open(f'{fname}.tbl', 'w') as f:
					f.write(str(t))
				# Log the html to parse manually later
				with open(f'{fname}.html', 'w') as f:  # added the '2'. Means skip cuz hopefully getting latlong now
					f.write(response.text)
				continue
		# check if still need to get latlong
		if 'Latitude' not in row.keys():  # only Lat good enough?
			if getlatlong(row, response.text):
				print(f'NEW LATLONG {c}:\t{row}')
				with open('newlatlong.txt', 'a') as f:
					f.write(str(row) + '\n')
			else:
				# Still failed to get lat long
				print('still no latlong')
				advanceurl = False
				continue

		# latlong is 0.0000: https://web.archive.org/web/20140724100239/http://postcode.my/melaka-melaka-jabatan-anti-malaria-75584.html
		try:
			if float(row['Latitude']) == 0 and float(row['Longitude']) == 0:
				print(f'latlong zeroes:\t{row}')
				advanceurl = False
				continue
		except KeyError:
			# lat or long not even in row
			advanceurl = False
			continue

		# latlong might be empty: https://web.archive.org/web/20150619125202/http://postcode.my/melaka-melaka-jabatan-perangkaan-75514.html
		# print(f'bad latlong: {row}')
		if isinstance(row['Latitude'], float):  # need check long too?
			if isnan(row['Latitude']):
				print(f'blank latlong: {row}')
				advanceurl = False
				continue
		# Successfully found scrape data. Show what we found on stdout
		print(f'{c}: {row}')
		# Write csv header if needed
		if c == 0:
			w.writerow(row.keys())
		# Write the row to the output file
		w.writerow(row.values())
		# Advance the counter
		c += 1
		# Save c to pick up where left off next run
		with open('startat.txt', 'w') as f:
			f.write(str(c))
	else:
		# Failed to get page. [s]Exit to alert programmer. TODO: handle pages (probably by logging) that fail like this[/s]
		print(f"Tried all snapshots for {url} and didn't succeed.")
		if re.search(r'Unusual Traffic Activity', response.text):
			print('reset captcha please')
			os.system('dunstify Postcode "Reset captcha!"')
			sys.exit()
		# Not unusual traffic, so just log it
		with open('failed.txt', 'a') as f:
			f.write(url + '\n')
		#sys.exit()

print('All done!')

# Was 13722 in the run, but then, on re-run, same url was:
# https://web.archive.org/web/20230815141130/https://postcode.my/kelantan-tumpat-kampung-pelas-merah-16210.html
# 13726: {'Location': 'Kampung Pelas Merah', 'Post Office': 'Tumpat', 'State': 'Kelantan', 'Postcode': '16210', 'Latitude': 6.195073, 'Longitude': 102.165736}
