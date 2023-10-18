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

def makeurlpagename(loc, po, st, pc):
	args = locals()
	for argname, argv in args.items():
		fixed = re.sub(r"\s*[).,'&]*$", '', argv.lower())  # usually ) should become a space (to then be converted to -), but not if at very end. Also gets other stuff like: ,)
		fixed = re.sub(r"[()@.\-&,–'`/]", ' ', fixed)
		fixed = re.sub(r'\s+', '-', fixed)  # used to be r' ' but then --- appeared instead of -, so hopefully \s ok or should be ' +'
		args[argname] = fixed
	return f"{args['st']}-{args['po']}-{args['loc']}-{args['pc']}"

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

def getpages_old():  # only part 1
	tree = ET.parse('listing_part2.xml')
	root = tree.getroot()  # root.tag, root.attrib
	ns = '{' + tree.getroot().tag[1:].split("}")[0] + '}'
	return root.findall(f'.//{ns}loc')

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

def check4():
	# check4 = go thru whole url list, checking data in wayback2_final.csv. If good, copy to wayback2_final2.csv (so data will be in order and know what have done and not done so far)
	# Report progress in report.txt or maybe bads.csv
	# Still do harvest by hand prior to running this
	def getstartat():  # copy of global code. TODO: transition to using this function and del global code version
		# TODO: handle case where want to re-run with same startat. Only if run `./harvest` will new figures be respected
		# startat = 11698
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

	def searchcsv_csvway(csvdata, location, postoffice, state, postcode):
		# keeps returning None when shouldn't. Can't figure it out!
		with open('searchcsv-tries.txt', 'w') as f:
			f.write(f'args: {location}, {postoffice}, {state}, {postcode}\n')
			f.write(f'arg types: {type(location)}, {type(postoffice)}, {type(state)}, {type(postcode)}\n')
			c = 0
			for row in csvdata:
				c += 1
				#print(row)
				f.write(f'{row}\n')
				f.write(f"row: {row['Location']}, {row['Post Office']}, {row['State']}, {row['Postcode']}\n")
				f.write(f"row type(s: {type(row['Location'])}, {type(row['Post Office'])}, {type(row['State'])}, {type(row['Postcode'])}\n")
				if row['Location'] == location and row['Post Office'] == postoffice and row['State'] == state and row['Postcode'] == postcode:
					with open('searchcsv-successes.txt', 'w') as fh:
						fh.write(f"found it at {c}!\n")  # one time say 1, next 2. Seems unlikely this is correct
					return row  # This will be the first. Should check for more.
				elif str(row['Location']) == str(location) and str(row['Post Office']) == str(postoffice) and str(row['State']) == str(state) and str(row['Postcode']) == str(postcode):
					f.write("type issue!\n")
					f.close()
					sys.exit()
					return row
			f.write(f'searched {c} rows')  # why when fails it says 4296???
		return None

	final1_fh = open('./wayback2_final1.csv', 'r')  # must manually add header (and it was down in it (the top of what was allsofar.csv). Moved it.)
	csvdata = csv.DictReader(final1_fh)
	outfile = open('output.csv', 'w')
	w = csv.writer(outfile)
	good_fh = open('good.csv', 'w')
	goodw = csv.writer(good_fh)
	bad_fh = open('bad.csv', 'w')
	badw = csv.writer(bad_fh)
	s = requests.Session()
	getnulls = False
	if getnulls:
		cur = dbexe_list('select url from postcode where Longitude isnull or Latitude isnull')
		urls = iter(cur.fetchall())
	else:
		urls = getpages(sourcefiles)
	startat = getstartat()
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
				print(f'{c}: Skipping: {url.text}')
				c += 1
				continue
			# Reset retrydelay if prev was successful, otherwise let it increment to wait longer and longer each time
			retrydelay = 0
		# Set success to False by default, so only if actually succeed further on will it be True
		success = False
		# Wait if going live
		livewait()
		if hasattr(url, 'text'):  # won't if not advancing url, and url already ok
			url = url.text
		# Get the page
		try:
			response = s.get(url)
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
			if retrydelay > 0:
				print(f'Waiting {retrydelay} seconds before retrying... ', end='')
				time.sleep(retrydelay)
				print('Done!')
			retrydelay += retrydelay_incr
			#raise
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
			raise

		# Process response
		if response.status_code == 200:
			# request successful
			if re.search(r'Unusual Traffic Activity', response.text):
				# but got captcha
				print(f'{c}: Captcha: {url}')
				os.system('dunstify Postcode "Reset captcha!"')
				sys.exit()
			else:
				# Got the html
				success = True
		else:
			# request unsuccessful
			if response.status_code == 404:
				# Not found
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 504:
				# Time out
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 429:
				# Too many requests
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 500:
				# Internal server error
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 523:
				# Unknown error
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 520:
				# Unknown error
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 503:
				# Service unavailable
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 524:
				# No reason whatsoever??? Happened when catcha'd out and went to real postcode.my site. Wait and try again
				# Happened again, real postcode.my site, but not captcha
				print(f'{c}: {response.status_code} {response.reason}: {url}')
				print(response)
			elif response.status_code == 502:
				# Bad gateway
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			else:
				# Unknown failed request, so alert programmer
				print(response.status_code)
				print(response.reason)
				print(response)
			continue

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
				#continue
				sys.exit(1)
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
					sys.exit()
				#continue
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
					fname = re.sub('/', '+', f'{url}-{tcount}')
					# Log the table for debugging (can del if always just the search form)
					with open(f'{fname}.tbl', 'w') as f:
						f.write(str(t))
					# Log the html to parse manually later
					with open(f'{fname}.html', 'w') as f:  # added the '2'. Means skip cuz hopefully getting latlong now
						f.write(response.text)
					#continue
					sys.exit(1)
			# check if still need to get latlong
			if 'Latitude' not in row.keys():  # only Lat good enough?
				if getlatlong(row, response.text):
					print(f'NEW LATLONG {c}:\t{row}')
					with open('newlatlong.txt', 'a') as f:
						f.write(str(row) + '\n')
					# debug
					print("since shouldn't happen anymore")
					sys.exit(1)
				else:
					# Still failed to get lat long
					print('still no latlong')
					#continue
					sys.exit(1)

			# latlong is 0.0000: https://web.archive.org/web/20140724100239/http://postcode.my/melaka-melaka-jabatan-anti-malaria-75584.html
			try:
				if float(row['Latitude']) == 0 and float(row['Longitude']) == 0:
					print(f'latlong zeroes:\t{row}')
					#continue
					sys.exit(1)
			except KeyError:
				# lat or long not even in row
				sys.exit(1)
			#continue

			# latlong might be empty: https://web.archive.org/web/20150619125202/http://postcode.my/melaka-melaka-jabatan-perangkaan-75514.html
			# print(f'bad latlong: {row}')
			if isinstance(row['Latitude'], float):  # need check long too?
				if isnan(row['Latitude']):
					print(f'blank latlong: {row}')
					#continue
					sys.exit(1)
			# Successfully found scrape data. Show what we found on stdout
			print(f'{c}: {row}')
			# Look for data in csv file
			#csvrow = searchcsv(csvdata, row['Location'], row['Post Office'], row['State'], row['Postcode'])
			#if csvrow is None:
			#	# Should never happen. No csv data found. Log it
			#	print(f"No csv data found for loc: {row['Location']}, po: {row['Post Office']}, st: {row['State']}, postcode: {row['Postcode']}")
			#	sys.exit(1)
			#elif float(csvrow['Latitude']) == row['Latitude'] and float(csvrow['Longitude']) == row['Longitude']:  # TODO: make the types the same to begin with. Make sure writerow does same thing if str or float
			#	# Good
			#	goodw.writerow(csvrow.values())
			#else:
			#	# Report if lat or long different
			#	print(f"Lat/long different - live vs csv:\n\t{row['Latitude']},\t{row['Longitude']}\n\t{csvrow['Latitude']},\t{csvrow['Longitude']}")
			#	#print(type(csvrow['Latitude']), type(row['Latitude']), type(csvrow['Longitude']), type(row['Longitude'])
			#	# Was: class 'str'> <class 'float'> <class 'str'> <class 'float'>)
			#	badw.writerow(csvrow.values())
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
			# Will no longer get here ever. TODO: get rid of this else block and no more if success (just move block over 1 tab to left)
			# Failed to get page. [s]Exit to alert programmer. TODO: handle pages (probably by logging) that fail like this[/s]
			print(f"Tried for {url} and didn't succeed.")
			if re.search(r'Unusual Traffic Activity', response.text):
				print('reset captcha please')
				os.system('dunstify Postcode "Reset captcha!"')
				sys.exit()
			# Not unusual traffic, so just log it
			with open('failed.txt', 'a') as f:
				f.write(url + '\n')
	#sys.exit()
	print('All done!')


# After ran check2, since had run get2 for a bit, had already d/led some good data, so remove. Hmm, check3 only removed a few (2902 vs 2911). Maybe correct?
def check3():
	with open('./allsofar.csv') as f:
		csvdata = csv.DictReader(f)
		for row in csvdata:
			pagename = makeurlpagename(row['Location'], row['Post Office'], row['State'], row['Postcode'])  # no extension yet
			#print(pagename, end='')
			url = f'https://postcode.my/{pagename}.html'  # remove this url from scrapethis.txt
			#print(f'rem: {url}')
			remurl_fh.write(f'{url}\n')
	# Remove urls from urls.txt
	os.system(f'sort ./scrapethis.txt > /tmp/a; sort /tmp/wayback2-remove-urls.txt > /tmp/b; comm -23 /tmp/a /tmp/b > scrapethis.txt')

# Similar to checkallcsv() but cleans scrapethis.txt of good urls. (Requires scrapethis.txt from check1 copied to
# ./firstcheck.) No longer checks if url isn't in scrapethis.txt, as
# assumes already done by check1. Only checks if latitude in bads.txt (manually moved to ./firstcheck) is in new ok
# range. New purged.txt file will now contain new good rows. Manually cat this to old purged.txt (manually copied to
# ./firstcheck). New scrapethis.txt can then be used by get2.
def checkallcsv2():
	def goodlatlong(row, latlong, url):  # url just for debugging, so remove
		# doesn't exist at all
		try:
			l = row[latlong]
		except:
			# no lat or long, so fail this row, i.e. keep it in urls.txt
			# return False
			# never happens; I think is None in this case?
			raise
		if l is None:
			# doesn't exist
			# Example: Add Review  Report Error  (adsbygoogle = window.adsbygoogle || []).push({});,Parit 30 (Jalan Pantai),Kuala Kurau,Perak,34350
			return False
		# isn't a number
		try:
			float(l)
		except ValueError:
			# example: each value is field name (first row of csv file?)
			print(f'v: "{l}" is not a number')
			print(row)
			return False
		except TypeError:
			# huh? I thought this happened, but now doesn't anymore???
			print(f't: "{l}" is not a number')
			print(row)
			sys.exit()
		# Ok, it exists, but is it zero?
		l = float(l)
		if l == 0:
			print(f'{l} is zero')
			print(row)
			sys.exit()
		elif l < 0:
			# funny example: Kampung Padang,Temangan,Kelantan,18400,-0.95,100.353056 (should be 5.701914, 102.15108)
			#print(f'{l} is negative')
			#print(row)
			#print(url)
			return False
		elif latlong == 'Latitude' and (l < 1 or l >= 7):
			#print(f'lat {l} < 1 or >= 7')
			#print(row)
			return False
		elif latlong == 'Longitude' and (l < 99 or l >= 119):
			print(f'long {l} < 99 or >= 119')
			print(row)
			print(url)
			sys.exit()
			return False
		return True

	# iterate bads.csv, removing url from scrapethis.txt if that row's data is good
	with open('./firstcheck/bads.csv') as f:  # TODO: bads.csv lacked header, so added it manually
		csvdata = csv.DictReader(f)
		for row in csvdata:
			pagename = makeurlpagename(row['Location'], row['Post Office'], row['State'], row['Postcode'])  # no extension yet
			#print(pagename, end='')
			url = f'https://postcode.my/{pagename}.html'
			# latitude good?
			if not goodlatlong(row, 'Latitude', url):
				bads_w.writerow(row.values())  # just for debugging. See rejected rows. (Ha, check2 uses this now.)
				continue  # not good so keep in url.txt
			# longitude good?
			if not goodlatlong(row, 'Longitude', url):
				bads_w.writerow(row.values())  # just for debugging. See rejected rows
				continue  # not good so keep in url.txt
			# data (assumed) good, so remove url. Also, copy data to purged.csv
			#print(f'rem: {url}')
			remurl_fh.write(f'{url}\n')
			purged.append(row)
	# Write to purged.csv file
	for row in purged:
		print(f'writing: {row}')
		purged_w.writerow(row.values())
	# Remove urls from urls.txt
	os.system(f'sort ./firstcheck/scrapethis.txt > /tmp/a; sort /tmp/wayback2-remove-urls.txt > /tmp/b; comm -23 /tmp/a /tmp/b > scrapethis.txt')

# Iterates allsofar.csv (assumes made by get1 phase which completed), constructs postcode.my url from each row. If error
# found (includes url not in urls.txt (constructed here; should be considered a temp file and moved to /tmp)), log it
# (to bads.txt). If error not found, url saved to /tmp/wayback2-remove-urls.txt , and csv row saved to purged.csv . This
# is our latest, greatest data file. From urls.txt and wayback2-remove-urls.txt, construct scrapethis.txt which is used
# by get2 phase to get rest of csv data. Note: if "good" data found on wayback machine differs from live site, data will
# still be wrong. Use check4 to check for this.
def checkallcsv():
	def geturls(s):
		tree = ET.parse(s)
		root = tree.getroot()  # root.tag, root.attrib
		ns = '{' + tree.getroot().tag[1:].split("}")[0] + '}'
		return root.findall(f'.//{ns}loc')

	def goodlatlong(row, latlong, url):  # url just for debugging, so remove
		# doesn't exist at all
		try:
			l = row[latlong]
		except:
			# no lat or long, so fail this row, i.e. keep it in urls.txt
			# return False
			# never happens; I think is None in this case?
			raise
		if l is None:
			# doesn't exist
			# Example: Add Review  Report Error  (adsbygoogle = window.adsbygoogle || []).push({});,Parit 30 (Jalan Pantai),Kuala Kurau,Perak,34350
			return False
		# isn't a number
		try:
			float(l)
		except ValueError:
			# example: each value is field name (first row of csv file?)
			print(f'v: "{l}" is not a number')
			print(row)
			return False
		except TypeError:
			# huh? I thought this happened, but now doesn't anymore???
			print(f't: "{l}" is not a number')
			print(row)
			sys.exit()
		# Ok, it exists, but is it zero?
		l = float(l)
		if l == 0:
			print(f'{l} is zero')
			print(row)
			sys.exit()
		elif l < 0:
			# funny example: Kampung Padang,Temangan,Kelantan,18400,-0.95,100.353056 (should be 5.701914, 102.15108)
			#print(f'{l} is negative')
			#print(row)
			#print(url)
			return False
		elif latlong == 'Latitude' and (l < 1 or l >= 7):
			#print(f'lat {l} < 1 or >= 7')
			#print(row)
			return False
		elif latlong == 'Longitude' and (l < 99 or l >= 119):
			print(f'long {l} < 99 or >= 119')
			print(row)
			print(url)
			sys.exit()
			return False
		return True

	# make urls.txt. This file begins full of all urls (from both part1 and 2) in expected, i.e. each file reversed, order.
	with open('urls.txt', 'w') as f:
		for s in sourcefiles:
			urls = geturls(s)
			while True:
				try:
					url = urls.pop()
				except IndexError:
					# empty list
					break
				f.write(f'{url.text}\n')

	# iterate allsofar.csv, removing url from urls.txt if that row's data is good
	with open('allsofar.csv') as f:
		csvdata = csv.DictReader(f)
		for row in csvdata:
			pagename = makeurlpagename(row['Location'], row['Post Office'], row['State'], row['Postcode'])  # no extension yet
			#print(pagename, end='')
			url = f'https://postcode.my/{pagename}.html'
			# latitude good?
			if not goodlatlong(row, 'Latitude', url):
				bads_w.writerow(row.values())  # just for debugging. See rejected rows
				continue  # not good so keep in url.txt
			# longitude good?
			if not goodlatlong(row, 'Longitude', url):
				bads_w.writerow(row.values())  # just for debugging. See rejected rows
				continue  # not good so keep in url.txt
			# Exception(s) Commented out, so url not found (uncomment out to find url), so scrape again and consider bad data (do not put into purged.csv)
			#if url == 'https://postcode.my/johor-segamat-kampung-bukit-seraya-85000.html':
			#	url = 'https://postcode.my/johor-segamat-kampung-bukitseraya-85000.html'  # postcode.my mistake in url (missing hyphen)
			#elif url == 'https://postcode.my/johor-segamat-jalan-lee-kay-hoh-85000.html':
			#	url = 'https://postcode.my/johor-segamat-jalanlee-kay-hoh-85000.html'  # postcode.my mistake in url (missing hyphen)
			#elif url == 'https://postcode.my/johor-segamat-jalan-jaafar-hamid-85000.html':
			#	url = 'https://postcode.my/johor-segamat-jalanjaafar-hamid-85000.html'  # postcode.my mistake in url (missing hyphen)
			#elif url == 'https://postcode.my/wilayah-persekutuan-kuala-lumpur-jalan-sultan-mizan-zainal-abidin-jalan-ibadah--50480.html':
			#	url = 'https://postcode.my/wilayah-persekutuan-kuala-lumpur-jalan-sultan-mizan-zainal-abidin-jalan-ibadah-50480.html'  # postcode.my mistake on page (double close parens)
			# Other discrepancies (handle by removing from allsofar.csv)
			#
			# {'Location': 'Sundar', 'Post Office': 'Sundar', 'State': 'Sarawak', 'Postcode': '98800', 'Latitude': '4.897012', 'Longitude': '115.2557759'}
			# https://postcode.my/sarawak-sundar-sundar-98800.html darn it, happened to find this case: lat and long slightly different on live site 4.8893404, 115.2075526
			# Another interesting case: UITM cawangan Bandar Seri Iskandar,Bandar Seri Iskandar,Perak,32600,4.3586668,100.9672776
			# got from wayback machine https://web.archive.org/web/20140720225130/https://postcode.my/perak-bandar-seri-iskandar-uitm-cawangan-bandar-seri-iskandar-32610.html
			# Note how postcode is different! Old postcode.my site was wrong.

			# search for url in urls.txt
			if url not in open('urls.txt').read():
				# url not found, so leave url. Do not copy to purged.csv, as there's some error in the row. Examples:
				# https://postcode.my/perak-bandar-seri-iskandar-uitm-cawangan-bandar-seri-iskandar-32600.html - postcode is 32610 in real url
				# https://postcode.my/selangor-subang-jaya-subang-jaya-usj-9-11-47610.html - postcode is 47620 in real url
				# two [email-protected]'s
				print(f'{url} -> {row}')
				bads_w.writerow(row.values())  # just for debugging. See rejected rows
			else:
				# url found and data (assumed) good (remove above "other discrepancies" by hand in purged.csv), so remove url. Also, copy data to purged.csv
				#print(f'rem: {url}')
				remurl_fh.write(f'{url}\n')
				purged.append(row)
	# Write to purged.csv file
	for row in purged:
		print(f'writing: {row}')
		purged_w.writerow(row.values())
	# Remove urls from urls.txt
	os.system(f'sort urls.txt > /tmp/a; sort /tmp/wayback2-remove-urls.txt > /tmp/b; comm -23 /tmp/a /tmp/b > scrapethis.txt')

# get2 only. Scrape urls off original site only, no wayback machine
def proc_urls(urls):
	global c  # count of urls; some possibly already skipped
	# Loop through all urls
	success = True
	while True:
		if success:
			# Get next url if prev was successful (or on very first url), otherwise keep it the same to try again
			try:
				url = next(urls)
			except StopIteration:
				break
			# Reset retrydelay if prev was successful, otherwise let it increment to wait longer and longer each time
			retrydelay = 0
		# Set success to False by default, so only if actually succeed further on will it be True
		success = False
		# Wait if going live
		livewait()
		# Get the page
		try:
			response = s.get(url)
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
			if retrydelay > 0:
				print(f'Waiting {retrydelay} seconds before retrying... ', end='')
				time.sleep(retrydelay)
				print('Done!')
			retrydelay += retrydelay_incr
			#raise
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
			raise

		# Process response
		if response.status_code == 200:
			# request successful
			if re.search(r'Unusual Traffic Activity', response.text):
				# but got captcha
				print(f'{c}: Captcha: {url}')
				sys.exit()
			else:
				# Got the html
				success = True
		else:
			# request unsuccessful
			if response.status_code == 404:
				# Not found
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 504:
				# Time out
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 429:
				# Too many requests
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 500:
				# Internal server error
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 523:
				# Unknown error
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 520:
				# Unknown error
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 503:
				# Service unavailable
				print(f'{c}: {response.status_code} {response.reason}: {url}')
			elif response.status_code == 524:
				# No reason whatsoever??? Happened when catcha'd out and went to real postcode.my site. Wait and try again
				# Happened again, real postcode.my site, but not captcha
				print(f'{c}: {response.status_code} {response.reason}: {url}')
				print(response)
			elif response.status_code == 502:
				# Bad gateway
				print(f'{c}: {response.status_code} {response.reason}: {url}')
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
				#continue
				sys.exit(1)
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
					sys.exit()
					#continue
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
					fname = re.sub('/', '+', f'{url}-{tcount}')
					# Log the table for debugging (can del if always just the search form)
					with open(f'{fname}.tbl', 'w') as f:
						f.write(str(t))
					# Log the html to parse manually later
					with open(f'{fname}.html', 'w') as f:  # added the '2'. Means skip cuz hopefully getting latlong now
						f.write(response.text)
					#continue
					sys.exit(1)
			# check if still need to get latlong
			if 'Latitude' not in row.keys():  # only Lat good enough?
				if getlatlong(row, response.text):
					print(f'NEW LATLONG {c}:\t{row}')
					with open('newlatlong.txt', 'a') as f:
						f.write(str(row) + '\n')
					# debug
					print("since shouldn't happen anymore")
					sys.exit(1)
				else:
					# Still failed to get lat long
					print('still no latlong')
					#continue
					sys.exit(1)

			# latlong is 0.0000: https://web.archive.org/web/20140724100239/http://postcode.my/melaka-melaka-jabatan-anti-malaria-75584.html
			try:
				if float(row['Latitude']) == 0 and float(row['Longitude']) == 0:
					print(f'latlong zeroes:\t{row}')
					#continue
					sys.exit(1)
			except KeyError:
				# lat or long not even in row
				sys.exit(1)
				#continue

			# latlong might be empty: https://web.archive.org/web/20150619125202/http://postcode.my/melaka-melaka-jabatan-perangkaan-75514.html
			# print(f'bad latlong: {row}')
			if isinstance(row['Latitude'], float):  # need check long too?
				if isnan(row['Latitude']):
					print(f'blank latlong: {row}')
					#continue
					sys.exit(1)
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
			print(f"Tried for {url} and didn't succeed.")
			if re.search(r'Unusual Traffic Activity', response.text):
				print('reset captcha please')
				os.system('dunstify Postcode "Reset captcha!"')
				sys.exit()
			# Not unusual traffic, so just log it
			with open('failed.txt', 'a') as f:
				f.write(url + '\n')
		#sys.exit()
	print('All done!')

# Get list of snapshots from the wayback machine
#site = "https://postcode.my"
#user_agent = "Mozilla/5.0 (Windows NT 5.1; rv:40.0) Gecko/20100101 Firefox/40.0"
#print('Connecting to wayback api... ', end='')
#cdx = WaybackMachineCDXServerAPI(site, user_agent)
#print('Done!')
#print('Getting snapshot urls... ', end='')
#snapshots = list(cdx.snapshots())
#snapshots.reverse()
#print('Done!')

########
# MAIN #
########

trywayback = False

if job == 'get1':
	trywayback = True
	# Set up requests session and output csv file
	s = requests.Session()
	outfile = open('output.csv', 'w')
	w = csv.writer(outfile)
	# Get list of urls to scrape
	# urls = getpages(sourcefiles)
	urls = getpages_old()
	# get1 continues below this if block
elif job == 'check' or job == 'check1':
	remurl_fh = open('/tmp/wayback2-remove-urls.txt', 'w')
	bads_fh = open('bads.csv', 'w')
	bads_w = csv.writer(bads_fh)
	purged_fh = open('purged.csv', 'w')
	purged_w = csv.writer(purged_fh)
	purged = []
	checkallcsv()
	sys.exit()
elif job == 'check2':
	remurl_fh = open('/tmp/wayback2-remove-urls.txt', 'w')
	bads_fh = open('bads.csv', 'w')
	bads_w = csv.writer(bads_fh)
	purged_fh = open('purged.csv', 'w')
	purged_w = csv.writer(purged_fh)
	purged = []
	checkallcsv2()
	sys.exit()
elif job == 'check3':
	remurl_fh = open('/tmp/wayback2-remove-urls.txt', 'w')
	check3()
	sys.exit()
elif job == 'check4':
	conn = initdb(dbfile)
	check4()
	sys.exit()
elif job == 'get2':  # When completed, cat purged.csv allsofar.csv > wayback2_final1.csv (instead of purged.csv, I used post-check2-latest-greatest-csv-purged-of-all-badness.csv)
	# should check if user set things up properly. See `harvest` for details.
	# Set up requests session and output csv file
	s = requests.Session()
	outfile = open('output.csv', 'w')
	w = csv.writer(outfile)
	# Get list of urls to scrape
	urls = fileinput.input(['scrapethis.txt'])
	# get2 continues below this if block
else:
	print('no job. Take day off.')
	sys.exit(1)

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

# get2 only
if job == 'get2':
	proc_urls(urls)
	sys.exit()

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
