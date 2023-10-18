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
