# University of Texas at Austin - QC report (2026-11-18)

- buildings: **150**  by type: {'apartment': 90, 'dorm': 2, 'student_housing': 15, 'condo': 34, 'co_op': 9}
- by area: {'West Campus': 117, 'East Campus': 11, 'North Campus': 9, 'Downtown Austin': 4, 'Riverside': 4, 'Hyde Park': 4, None: 1}
- coord methods: {'places_pin+footprint_centroid': 12, 'nad_address+footprint_centroid': 138}
- with amenities: 122  (median 10)
- price status: {'listed': 99, 'not_publicly_listed': 51}  unit rows: 2219
- with aliases: 50

## Coordinates needing a manual right-click check

- The Block on 25 East (702 West 25th Street Austin, TX 78705) - nad_address+footprint_centroid
- Town Lake (1109 S Pleasant Valley Rd, Austin, TX 78741) - nad_address+footprint_centroid
- Ballpark North (4600 Elmont Dr, Austin, TX 78741) - nad_address+footprint_centroid
- Buena Vista Condo (1908 San Antonio St APT 312
Austin, TX 78705) - nad_address+footprint_centroid
- Hyde Park Apartments (4410 Avenue F, Austin, TX 78751,) - nad_address+footprint_centroid
- The Eastwood (2901 Swisher St, Austin, TX 78705, USA) - nad_address+footprint_centroid

## Listings likely undercounted (feed platform with no adapter rows, or page shows more prices than rows)

listing source per building: {'none': 37, 'text_plan_list': 13, 'appfolio_smart': 13, 'uptown_realty': 13, 'llm_page_read': 12, 'acc_lightning': 11, 'landmark': 7, 'duda_appfolio_feed': 6, 'sightmap': 5, 'villas_wp': 5, 'repli360_feed': 4, 'rentcafe_inline': 4, 'wp_entrata_json': 3, 'realpage_cms_proxy': 2, 'sinclair_wp': 2, 'ion_wp': 2, 'webflow_cms_floorplans': 1, 'fp_units_modal_v2': 1, 'sgs_static': 1, 'ballpark_static': 1, 'gogetter_wc_floorplans': 1, 'rambler_lvbode': 1, 'vsg_static': 1, 'webflow_product7': 1, 'jonah_detail_json': 1, 'mmc_ajax': 1, 'ninehundred_static': 1}

- The Mark Austin - 36 rows via landmark - page_shows_92_distinct_prices_vs_36_rows - tried: landmark=36
- Nueces - 0 rows via None - feed_platform_but_no_adapter_rows:entrata; needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: entrata_pp=0, text_plan_list=0
- Torre - 40 rows via llm_page_read - feed_platform_but_no_adapter_rows:entrata - tried: entrata_pp=0, text_plan_list=0
- Mark Embers - 7 rows via appfolio_smart - page_shows_22_distinct_prices_vs_7_rows - tried: duda_appfolio_feed=0, appfolio_smart=7
- Moontower - 17 rows via landmark - page_shows_58_distinct_prices_vs_17_rows - tried: landmark=17
- Grandmarc Austin - 0 rows via None - feed_platform_but_no_adapter_rows:entrata; needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: webflow_cms_floorplans=0, webflow_cms_floorplans=0, entrata_pp=0, text_plan_list=0
- Legacy on Rio - 33 rows via landmark - page_shows_84_distinct_prices_vs_33_rows - tried: landmark=33
- Capitol Living - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: jsonld_offers=0, text_plan_list=0
- Rise at West Campus - 0 rows via None - feed_platform_but_no_adapter_rows:entrata; blocked_bot_wall_needs_headed_browser:entrata_pp; needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: rise_units=0, entrata_pp=0, text_plan_list=0
- Taos Co-op - 5 rows via llm_page_read - feed_platform_but_no_adapter_rows:entrata; page_shows_33_distinct_prices_vs_5_rows - tried: entrata_pp=0, text_plan_list=0
- 21st Co-Op - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- Waterford Condos - 3 rows via uptown_realty - page_shows_25_distinct_prices_vs_3_rows - tried: uptown_realty=3
- Texan 26 - 0 rows via None - feed_platform_but_no_adapter_rows:entrata; needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: webflow_cms_floorplans=0, entrata_pp=0, text_plan_list=0
- Warwick Apartments - 6 rows via appfolio_smart - page_shows_22_distinct_prices_vs_6_rows - tried: duda_appfolio_feed=0, appfolio_smart=6
- Town Lake - 0 rows via None - realtor page match unverified (address differs); left unpriced - tried: uptown_realty=7, webflow_cms_floorplans=0
- Halstead Co-op & Nueces - 6 rows via llm_page_read - feed_platform_but_no_adapter_rows:entrata; page_shows_33_distinct_prices_vs_6_rows - tried: entrata_pp=0, text_plan_list=0
- Volume - 7 rows via rentcafe_inline - page_shows_21_distinct_prices_vs_7_rows - tried: rentcafe_inline=7
- Sentral East Austin - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- 2400 Nueces Apartments - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: university_rates=0, text_plan_list=0
- Pearl Street Co-Op - 5 rows via llm_page_read - feed_platform_but_no_adapter_rows:entrata - tried: entrata_pp=0, text_plan_list=0
- College Houses Cooperatives - 19 rows via llm_page_read - feed_platform_but_no_adapter_rows:entrata - tried: entrata_pp=0, text_plan_list=0
- Piazza Novana - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- EASTGATE CONDO, perfect for House Staff at Dell/St. David's. Limited-Time Housestaff Lease Discount - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- Dos Rios - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: nothing
- Su Casa Apartment Homes - 4 rows via appfolio_smart - page_shows_22_distinct_prices_vs_4_rows - tried: duda_appfolio_feed=0, appfolio_smart=4
- Monticello Studios - 0 rows via None - feed_platform_but_no_adapter_rows:appfolio; needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: westside_prose=0, appfolio_smart=0, text_plan_list=0
- New Guild Co-operative - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- The Quarters Nueces House - 29 rows via llm_page_read - feed_platform_but_no_adapter_rows:entrata; blocked_bot_wall_needs_headed_browser:entrata_pp - tried: entrata_pp=0, text_plan_list=5
- Villas on 24th - 11 rows via wp_entrata_json - adapter_rows_unpriced_but_page_shows_prices - tried: wp_entrata_json=11, entrata_pp=0, text_plan_list=0
- Grayson - 0 rows via None - feed_platform_but_no_adapter_rows:entrata; needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: entrata_pp=0, text_plan_list=0
- The Quarters Grayson House - 0 rows via None - feed_platform_but_no_adapter_rows:entrata; blocked_bot_wall_needs_headed_browser:entrata_pp; needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: entrata_pp=0, text_plan_list=0
- UT Speedway - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- Texan Tower Condos - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- Nob Hill Homes - 1 rows via appfolio_smart - page_shows_22_distinct_prices_vs_1_rows - tried: duda_appfolio_feed=0, appfolio_smart=1
- Blackstone Apartments - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: jsonld_offers=0, text_plan_list=0
- Greenwood Towers Condominiums - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- Texan 304 - 0 rows via None - feed_platform_but_no_adapter_rows:appfolio; needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: duda_appfolio_feed=0, text_plan_list=0
- Gateway 8 - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: nothing
- 31st Street Condominiums - 0 rows via None - feed_platform_but_no_adapter_rows:realpage; needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: realpage_sniff=0, text_plan_list=0
- The Quarters Karnes House - 0 rows via None - feed_platform_but_no_adapter_rows:entrata; blocked_bot_wall_needs_headed_browser:entrata_pp; page_shows_16_distinct_prices_vs_0_rows; needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: entrata_pp=0, text_plan_list=0
- The Quarters Sterling House - 0 rows via None - feed_platform_but_no_adapter_rows:entrata; blocked_bot_wall_needs_headed_browser:entrata_pp; page_shows_16_distinct_prices_vs_0_rows; needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: entrata_pp=0, text_plan_list=0
- French House - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- Presidio At Judge's Hill - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- 1883 Cameron & Montgomery House - 9 rows via llm_page_read - feed_platform_but_no_adapter_rows:entrata; blocked_bot_wall_needs_headed_browser:entrata_pp - tried: jsonld_offers=0, entrata_pp=0, text_plan_list=0
- Villas on 26th - 13 rows via llm_page_read - feed_platform_but_no_adapter_rows:sightmap,entrata; blocked_bot_wall_needs_headed_browser:entrata_pp - tried: vnue_grid_static=0, jsonld_offers=0, entrata_pp=0, text_plan_list=0
- San Remo - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: nothing
- Sandpiper Apartments - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- Fountain Terrace - 3 rows via realpage_cms_proxy - page_shows_17_distinct_prices_vs_3_rows; adapter_rows_unpriced_but_page_shows_prices - tried: realpage_cms_proxy=3, rentcafe_ysi=0, g5_sniff=0, entrata_pp=0, text_plan_list=0
- Hyde Park Apartments - 0 rows via None - realtor page match unverified (address differs); left unpriced - tried: uptown_realty=2
- Mosaic at Mueller - 3 rows via uptown_realty - page_shows_12_distinct_prices_vs_3_rows - tried: uptown_realty=3
- The G - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- Buena Vista Condominium - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: uptown_realty=0, text_plan_list=0
- Helios Co-Op - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- Sunchase Condos - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- Wedgewood Condos - 5 rows via text_plan_list - page_shows_25_distinct_prices_vs_5_rows - tried: text_plan_list=5
- Lenox Condos - 4 rows via text_plan_list - page_shows_25_distinct_prices_vs_4_rows; adapter_rows_unpriced_but_page_shows_prices - tried: text_plan_list=4
- Shane Michael Brooks - 0 rows via None - feed_platform_but_no_adapter_rows:appfolio; needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: duda_appfolio_feed=0, text_plan_list=0
- West Ridge Condos - 4 rows via text_plan_list - page_shows_25_distinct_prices_vs_4_rows; adapter_rows_unpriced_but_page_shows_prices - tried: text_plan_list=4
- Rio Flats - 0 rows via None - feed_platform_but_no_adapter_rows:appfolio; needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: text_plan_list=0
- The 34 at Helms - 0 rows via None - needs_case_by_case: no extractor rows (run with --llm, add an adapter, or save a rescue) - tried: nothing

## No amenity data (site missing / blocked / condo without a page)

- Vanderbilt Condos - blocked_or_empty - https://uptownrealtyaustin.com/communities/vanderbilt_condos/
- 21st Co-Op - no_website - https://collegehouses.org/listings/21st/
- Croix - ok - https://uptownrealtyaustin.com/communities/croix/
- The Block on Pearl North - no_website - None
- The Block on Leon - no_website - None
- The Block on 23rd - no_website - None
- Yugo Austin Nueces - blocked_or_empty - https://yugo.com/en-us/global/united-states-of-america/austin-tx/yugo-austin-nueces-?utm_source=googlemaps&utm_medium=organic
- EASTGATE CONDO, perfect for House Staff at Dell/St. David's. Limited-Time Housestaff Lease Discount - ok - http://www.prospectrealestate.com/
- Dos Rios - no_website - None
- Grayson - ok - https://www.quartersoncampus.com/Apartments/module/application_authentication/
- Buena Vista Condo - ok - https://uptownrealtyaustin.com/communities/buena_vista/
- UT Speedway - no_website - https://jnjrealestate.com/apt
- Parapet - ok - https://bramlettresidential.com/reso/TX/Austin/78705/048c899b6e4e21215726562786a2a914/Parapet-Condo
- Tree House - ok - https://uptownrealtyaustin.com/communities/treehouse/
- Texan Tower Condos - ok - https://bramlettresidential.com/reso/TX/Austin/78705/c0441085bcc7ef273dfb70fb96f75bfc/Texan-Tower-Condo-Amd
- Blackstone Apartments - ok - http://austinblackstoneapts.com/
- Red River Place Apartments - ok - https://uptownrealtyaustin.com/communities/red_river_apartments/
- Greenwood Towers Condominiums - ok - http://www.highrises.com/austin/greenwood-towers/
- Gateway 8 - no_website - None
- University Quarters - blocked_or_empty - https://gbatx.com/properties/university-quarters
- Presidio At Judge's Hill - ok - http://www.highrises.com/austin/presidio-at-judges-hill-condos/
- Littlefield House - ok - https://uptownrealtyaustin.com/communities/littlefield_house/
- San Remo - no_website - None
- Starwest Condos - ok - https://uptownrealtyaustin.com/communities/starwest/
- Hyde Park Apartments - ok - https://uptownrealtyaustin.com/communities/hyde_park_condominiums/
- The G - no_website - http://thegaustin.com/
- Salado Place - ok - https://uptownrealtyaustin.com/communities/salado_place/
- The 34 at Helms - no_website - None