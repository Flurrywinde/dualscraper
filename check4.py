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
