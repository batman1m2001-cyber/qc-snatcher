import re
import time
import pandas as pd
from databricks import sql  # avoid collision with built-in sql() function
from databricks.sdk.core import Config, oauth_service_principal

# --- Fuzzy match buffer ---
FUZZY_BUFFER_SECONDS = 5


def credential_provider(databricks_host, databricks_client_id, databricks_client_secret):
    config = Config(
        host=databricks_host,
        client_id=databricks_client_id,
        client_secret=databricks_client_secret,
    )
    return oauth_service_principal(config)

def databricks_query(databricks_host: str,
                     databricks_client_id: str,
                     databricks_client_secret: str,
                     databricks_sql_http_path: str,
                     query: str,
                     max_retries:int=3,
                     retry_delay:int=5):
    """Query data from databricks delta table throught sql warehouse

    Args:
        query (str): The SQL query to execute.
        max_retries (int, optional): The maximum number of retry attempts. Defaults to 3.
        retry_delay (int, optional): The delay between retry attempts in seconds. Defaults to 5.

    Raises:
        Exception: If the query fails after the maximum number of retries.

    Returns:
        list: The result rows from the query.
    """
    print(f"Executing query: {len(query)} chars")
    for attempt in range(max_retries):
        try:
            with sql.connect(
                server_hostname=databricks_host,
                http_path=databricks_sql_http_path,
                credentials_provider=lambda: credential_provider(databricks_host, databricks_client_id, databricks_client_secret),
            ) as connection:
                print(f"Connected to Databricks SQL warehouse on attempt {attempt + 1}/{max_retries}")
                cursor = connection.cursor()
                st_time = time.time()
                cursor.execute(query)
                elapsed = time.time() - st_time
                print(f"Query time: {elapsed:.1f}s")
                cols = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                df = pd.DataFrame(rows, columns=cols)
                print(f"Rows returned: {len(df)}")
                return df
        except Exception as e:
            print(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                print(f"Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                raise

def parser_filenames(audio_names: list) -> tuple[pd.DataFrame, list]:
    """Parse audio filenames to extract metadata.

    Args:
        audio_names (list): List of audio filenames.

    Returns:
        tuple[pd.DataFrame, list]: DataFrame with parsed metadata and list of filenames that failed to parse.
    """
    records = []
    parse_failures = []
    for name in audio_names:
        phone_match = re.search(r'_CLID_(\d+)', name)
        date_match = re.search(r'_D_(\d{4})-(\d{2})-(\d{2})_', name)
        time_match = re.search(r'_H_(\d{2})(\d{2})(\d{2})_', name)
        # New filename suffix carries CalltraceID trailing YES/NO:
        #   ..._CLID_<phone>_<queue>_<callcode>_<YES|NO>_<calltraceid>.wav
        # Optional capture keeps the old format (no trailing id) parseable
        # so a mixed batch doesn't drop rows during the rollout.
        pqcb_match = re.search(r'CLID_([^_]+)_+(-?\d+)_+(-?\d+)_(YES|NO)(?:_(\d+))?\.(wav|mp3)$', name)
        if not pqcb_match:
            parse_failures.append(name)
            continue
        raw_phone, queue_id, call_code, stop_bool, calltraceid_from_name, file_ext = pqcb_match.groups()
        closed_by = "AGENT" if stop_bool.upper() == "YES" else "CUSTOMER"
        if phone_match and date_match and time_match:
            y, m, d = date_match.groups()
            hh, mm, ss = time_match.groups()
            records.append({
                'audio_name': name,
                'phone': phone_match.group(1),
                'rawphone': raw_phone,
                'queueid': queue_id,
                'callcode': call_code,
                'closedby': closed_by,
                'year': int(y),
                'month': int(m),
                'day': int(d),
                'answertime': f"{y}-{m}-{d}T{hh}:{mm}:{ss}",
                # Parsed-but-unused: the calltraceid embedded in the new
                # filename suffix. Kept here so a future update can skip the
                # two-pass SQL match entirely when this is present.
                'calltraceid_from_name': calltraceid_from_name,
            })
        else:
            parse_failures.append(name)

    df_audio = pd.DataFrame(records)
    print(f"Parsed successfully: {len(df_audio)}")
    if parse_failures:
        print(f"Parse failed: {len(parse_failures)} (samples: {parse_failures[:3]})")
    print(f"Date range: {df_audio['answertime'].min()[:10]} to {df_audio['answertime'].max()[:10]}")
    return df_audio, parse_failures

def drop_ambiguous_keys(df_audio: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    """Drop all audio rows that share (phone, queueid, answertime) with another row.

    Không có cách disambiguate 1-1 với calltrace khi audio side có >1 file cùng khoá
    (cùng số điện thoại, cùng queue, cùng giây answertime). Loại bỏ toàn bộ group
    thay vì gán nhầm calltraceid.
    """
    if df_audio.empty:
        return df_audio, []
    key_cols = ['phone', 'queueid', 'year', 'month', 'day', 'answertime', 'calltraceid_from_name']
    dup_mask = df_audio.duplicated(subset=key_cols, keep=False)
    dropped_names = df_audio.loc[dup_mask, 'audio_name'].tolist()
    df_dedup = df_audio[~dup_mask].reset_index(drop=True)
    if dropped_names:
        n_groups = df_audio.loc[dup_mask].groupby(key_cols, sort=False).ngroups
        print(f"Dropped {len(dropped_names)} ambiguous audio files in {n_groups} duplicate (phone, queueid, timestamp, calltraceid) groups")
    return df_dedup, dropped_names

def escape_sql(value):
    if value is None:
        return value

    val = str(value)

    val = val.replace("'", "''")
    val = val.replace("\\", "\\\\")
    val = val.replace('"', '""')

    return f"'{val}'"


def create_partition_filter(df_audio: pd.DataFrame,
                            calltrace_table: str,
                            callcode_table: str) -> tuple[str, str, str, str]:
    """_summary_

    Args:
        df_audio (pd.DataFrame): _description_
        calltrace_table (str): _description_
        callcode_table (str): _description_

    Returns:
        tuple[str, str, str, str]: _description_
    """
    years = sorted(df_audio['year'].unique())
    months = sorted(df_audio['month'].unique())
    days = sorted(df_audio['day'].unique())
    PARTITION_FILTER = (
        f"year IN ({','.join(str(y) for y in years)}) "
        f"AND month IN ({','.join(str(m) for m in months)}) "
        f"AND day IN ({','.join(str(d) for d in days)})"
    )
    print(f"Partition filter: {PARTITION_FILTER}")

    # --- VALUES clause from in-memory df_audio ---
    st = time.time()
    values_parts = []
    for row in df_audio.itertuples(index=False):
        values_parts.append(
            f"({escape_sql(row.audio_name)},{escape_sql(row.phone)},{escape_sql(row.rawphone)},{escape_sql(row.closedby)},{escape_sql(row.calltraceid_from_name)},{row.queueid},{row.callcode},{row.year},{row.month},{row.day},{escape_sql(row.answertime)})"
        )
    VALUES_CLAUSE = ",".join(values_parts)
    print(f"VALUES clause built in {time.time()-st:.1f}s ({len(VALUES_CLAUSE)/1024/1024:.1f} MB)")

    # --- AUDIO CTE ---
    AUDIO_CTE = f"""
    audio AS (
        SELECT
            audio_name, phone, rawphone, closedby,
            calltraceid_from_name,
            CAST(queueid AS INT) AS queueid,
            CAST(callcode AS INT) AS callcode,
            CAST(year AS INT) AS year,
            CAST(month AS INT) AS month,
            CAST(day AS INT) AS day,
            CAST(answertime AS TIMESTAMP) AS answertime
        FROM VALUES
            {VALUES_CLAUSE}
        AS t(audio_name, phone, rawphone, closedby, calltraceid_from_name, queueid, callcode, year, month, day, answertime)
    )
    """

    # --- CALLTRACE CTE ---
    CALLTRACE_CTE = f"""
    calltrace_clean AS (
        SELECT
            calltraceid, customerid, answertime, closetime, queueid, year, month, day,
            regexp_extract(dnis, '^([0-9]+)', 1) AS clean_dnis,
            regexp_extract(ani, '^([0-9]+)', 1) AS clean_ani
        FROM {calltrace_table}
        WHERE {PARTITION_FILTER}
    )
    """

    CALLCODE_DETAILS_CTE = f"""
    callcode_details AS (
        SELECT callcode, callcodedetails, year, month, day
        FROM {callcode_table}
        WHERE {PARTITION_FILTER}
    )
    """

    print(f"AUDIO_CTE: ~{len(AUDIO_CTE)/1024/1024:.1f} MB")
    print(f"CALLTRACE_CTE: {len(CALLTRACE_CTE)} chars")
    print("SQL components ready.")

    return PARTITION_FILTER, AUDIO_CTE, CALLTRACE_CTE, CALLCODE_DETAILS_CTE

def create_pass_queries(AUDIO_CTE: str,
                        CALLTRACE_CTE: str,
                        CALLCODE_DETAILS_CTE: str) -> tuple[str, str]:
    
    PASS1_QUERY = f"""
    WITH {AUDIO_CTE},
    {CALLTRACE_CTE},
    {CALLCODE_DETAILS_CTE},
    joined AS (
        SELECT
            ct.calltraceid,
            ct.customerid,
            ct.answertime,
            ct.closetime,
            a.audio_name,
            a.queueid as raw_queueid,
            a.rawphone,
            a.closedby,
            cd.callcodedetails,
            ROW_NUMBER() OVER (
                PARTITION BY a.audio_name
                ORDER BY ct.calltraceid ASC
            ) AS rn
        FROM audio a
        LEFT JOIN calltrace_clean ct
            ON a.year = ct.year
            AND a.month = ct.month
            AND a.day = ct.day
            AND a.answertime = ct.answertime
            AND (a.phone = ct.clean_dnis OR a.phone = ct.clean_ani)
            AND a.queueid = ct.queueid
            AND a.calltraceid_from_name = ct.calltraceid
        LEFT JOIN callcode_details cd
            ON a.callcode = cd.callcode
            AND a.year = cd.year
            AND a.month = cd.month
            AND a.day = cd.day
    )
    SELECT calltraceid, answertime, closetime, customerid, audio_name, callcodedetails, raw_queueid, rawphone, closedby
    FROM joined
    WHERE rn = 1
    """
    
    PASS2_QUERY = f"""
    WITH {AUDIO_CTE},
    {CALLTRACE_CTE},
    {CALLCODE_DETAILS_CTE},
    exact_matched AS (
        SELECT a.audio_name
        FROM audio a
        INNER JOIN calltrace_clean ct
            ON a.year = ct.year
            AND a.month = ct.month
            AND a.day = ct.day
            AND a.answertime = ct.answertime
            AND (a.phone = ct.clean_dnis OR a.phone = ct.clean_ani)
            AND a.queueid = ct.queueid
            AND a.calltraceid_from_name = ct.calltraceid
    ),
    unmatched AS (
        SELECT a.*
        FROM audio a
        LEFT ANTI JOIN exact_matched e ON a.audio_name = e.audio_name
    ),
    fuzzy_candidates AS (
        SELECT
            u.audio_name,
            u.queueid as raw_queueid,
            u.rawphone,
            u.closedby,
            ct.calltraceid,
            ct.customerid,
            ct.answertime,
            ct.closetime,
            cd.callcodedetails,
            ABS(UNIX_TIMESTAMP(u.answertime) - UNIX_TIMESTAMP(ct.answertime)) AS time_diff_sec,
            ROW_NUMBER() OVER (
                PARTITION BY u.audio_name
                ORDER BY ABS(UNIX_TIMESTAMP(u.answertime) - UNIX_TIMESTAMP(ct.answertime))
            ) AS rn
        FROM unmatched u
        INNER JOIN calltrace_clean ct
            ON u.year = ct.year
            AND u.month = ct.month
            AND u.day = ct.day
            AND (u.phone = ct.clean_dnis OR u.phone = ct.clean_ani)
            AND u.queueid = ct.queueid
            AND u.calltraceid_from_name = ct.calltraceid
            AND ABS(UNIX_TIMESTAMP(u.answertime) - UNIX_TIMESTAMP(ct.answertime)) <= {FUZZY_BUFFER_SECONDS}
        LEFT JOIN callcode_details cd
            ON u.callcode = cd.callcode
            AND u.year = cd.year
            AND u.month = cd.month
            AND u.day = cd.day
    )
    SELECT calltraceid, answertime, closetime, customerid, audio_name, time_diff_sec, callcodedetails, raw_queueid, rawphone, closedby
    FROM fuzzy_candidates
    WHERE rn = 1
    """
    
    return PASS1_QUERY, PASS2_QUERY

def create_enrich_query(df_final: pd.DataFrame,
                        df_audio: pd.DataFrame,
                        PARTITION_FILTER: str,
                        databricks_calltrace_table: str,
                        databricks_tethys_allaction_table: str,
                        databricks_tethys_actionresult_table: str,
                        databricks_customer_contact_table: str):
    df_final['agent_name'] = df_final['audio_name'].apply(
        lambda x: re.match(r'E_(.+?)_D_', x).group(1) if re.match(r'E_(.+?)_D_', x) else None
    )
    df_final = df_final.merge(df_audio[['audio_name', 'phone']], on='audio_name', how='left')

    print(f"Prepared: {len(df_final)} rows, agents={df_final['agent_name'].notna().sum()}, phones={df_final['phone'].notna().sum()}")
    # --- Step 2: Build single VALUES clause ---
    df_eligible = df_final[df_final['calltraceid'].notna()].copy()

    st = time.time()
    values_parts = []
    for row in df_eligible.itertuples(index=False):
        agent = row.agent_name or ''
        phone = row.phone or ''
        ct_id = int(row.calltraceid)
        cid = row.customerid or ''
        values_parts.append(
            f"({escape_sql(row.audio_name)},{escape_sql(agent)},{escape_sql(phone)},{ct_id},{escape_sql(cid)})"
        )

    VALUES_ENRICH = ",".join(values_parts)
    print(f"VALUES clause: {len(VALUES_ENRICH)/1024/1024:.1f} MB built in {time.time()-st:.1f}s")
    # --- Step 3: Combined enrichment SQL ---
    ENRICH_QUERY = f"""
    WITH audio_data AS (
        SELECT audio_name, agent_name, phone, calltraceid, customerid
        FROM VALUES
            {VALUES_ENRICH}
        AS t(audio_name, agent_name, phone, calltraceid, customerid)
    ),
    -- Join calltrace ONCE to get closetime + queueid
    call_info AS (
        SELECT
            ad.audio_name, ad.agent_name, ad.phone, ad.customerid,
            ct.closetime,
            ct.queueid
        FROM audio_data ad
        INNER JOIN {databricks_calltrace_table} ct
            ON ad.calltraceid = ct.calltraceid
            AND ct.{PARTITION_FILTER}
    ),
    -- Action result name lookup (latest snapshot, deduplicated)
    ar_names AS (
        SELECT arid, actionresultdesc AS kqhd,
            ROW_NUMBER() OVER (PARTITION BY arid ORDER BY year DESC, month DESC, day DESC) AS rn
        FROM {databricks_tethys_actionresult_table}
    ),
    ar_lookup AS (
        SELECT arid, kqhd FROM ar_names WHERE rn = 1
    ),
    -- Branch 1: Tethys KQHD
    tethys_candidates AS (
        SELECT
            ci.audio_name,
            t.arid,
            t.actiondate,
            ABS(UNIX_TIMESTAMP(t.actiondate) - UNIX_TIMESTAMP(ci.closetime)) AS time_diff_sec,
            CASE t.arid
                WHEN 1    THEN 1
                WHEN 301  THEN 2
                WHEN 1119 THEN 3
                WHEN 302  THEN 4
                WHEN 273  THEN 5
                WHEN 274  THEN 6
                WHEN 1114 THEN 7
                WHEN 1115 THEN 8
                WHEN 1107 THEN 9
                WHEN 202  THEN 10
                WHEN 1112 THEN 11
                WHEN 205  THEN 12
                WHEN 1108 THEN 13
                WHEN 1113 THEN 14
                ELSE 999
            END AS priority_rank
        FROM call_info ci
        INNER JOIN {databricks_tethys_allaction_table} t
            ON ci.customerid = t.customeryid
            AND LOWER(ci.agent_name) = LOWER(t.username)
            AND t.{PARTITION_FILTER}
            AND t.actiondate >= ci.closetime
            AND t.actiondate <= ci.closetime + INTERVAL 30 MINUTES
        WHERE ci.customerid != ''
    ),
    tethys_ranked AS (
        SELECT *,
            ROW_NUMBER() OVER (
                PARTITION BY audio_name
                ORDER BY time_diff_sec ASC, priority_rank ASC, arid ASC
            ) AS rn
        FROM tethys_candidates
    ),
    tethys_final AS (
        SELECT audio_name, arid, actiondate AS tethys_actiondate, time_diff_sec AS tethys_time_diff_sec
        FROM tethys_ranked WHERE rn = 1
    ),
    -- Branch 2: Chính Chủ SĐT (phone-only lookup, no CIF constraint)
    -- Rule: SĐT được gọi ra thuộc chính chủ trên hệ thống = phone exists
    -- as a registered primary phone for ANY customer in customer_contact.
    -- Unpivot 16 phone columns vào 1 set DISTINCT để equi-join với ci.phone
    -- (tránh BroadcastNestedLoopJoin do top-level OR không có equi-key).
    chinh_chu_phones AS (
        SELECT DISTINCT phone FROM (
            SELECT stack(16,
                phone_1, phone_2, t24_mobile_clear, ebank_mobile_clear,
                i2b_mobile, w4_mobile_1, w4_mobile_2, w4_mobile_3,
                crm_mobile_1, crm_mobile_2, crm_mobile_3,
                finnone_mobile_1, finnone_mobile_2,
                los_mobile_1, los_mobile_2, phone_correct_from_cc
            ) AS phone
            FROM {databricks_customer_contact_table}
            WHERE business_date = '2026-04-01'
        ) t
        WHERE phone IS NOT NULL AND phone != ''
    ),
    chinh_chu AS (
        SELECT
            ci.audio_name,
            (cp.phone IS NOT NULL) AS is_chinh_chu
        FROM call_info ci
        LEFT JOIN chinh_chu_phones cp ON ci.phone = cp.phone
        WHERE ci.phone != ''
    )
    -- Combine all enrichments: output KQHD name (not arid number)
    SELECT
        ci.audio_name,
        ar.kqhd,
        tf.tethys_actiondate,
        tf.tethys_time_diff_sec,
        ch.is_chinh_chu,
        ci.queueid
    FROM call_info ci
    LEFT JOIN tethys_final tf ON ci.audio_name = tf.audio_name
    LEFT JOIN ar_lookup ar ON tf.arid = ar.arid
    LEFT JOIN chinh_chu ch ON ci.audio_name = ch.audio_name
    """
    return ENRICH_QUERY

def query_pass1(databricks_host: str,
                databricks_sql_http_path: str,
                databricks_client_id: str,
                databricks_client_secret: str,
                pass1_query: str,
                real_total: int) -> pd.DataFrame:
    print(f"\n=== Pass 1: Exact Match (deduplicated) ===")
    df_pass1 = databricks_query(
        databricks_host=databricks_host,
        databricks_sql_http_path=databricks_sql_http_path,
        databricks_client_id=databricks_client_id,
        databricks_client_secret=databricks_client_secret,
        query=pass1_query
    )

    matched_count = df_pass1['calltraceid'].notna().sum()
    unmatched_count = df_pass1['calltraceid'].isna().sum()
    total = len(df_pass1)
    print(f"Total audio files: {total}")
    print(f"Matched: {matched_count} ({matched_count/total*100:.1f}%)")
    print(f"Unmatched: {unmatched_count} ({unmatched_count/total*100:.1f}%)")
    assert total == real_total, f"Expected {real_total} rows but got {total} — dedup logic may be incorrect"
    return df_pass1

def query_pass2(databricks_host: str,
                databricks_sql_http_path: str,
                databricks_client_id: str,
                databricks_client_secret: str,
                pass2_query: str) -> pd.DataFrame:
    print(f"\n=== Pass 2: Fuzzy Match (±{FUZZY_BUFFER_SECONDS}s) ===")
    df_pass2 = databricks_query(
        databricks_host=databricks_host,
        databricks_sql_http_path=databricks_sql_http_path,
        databricks_client_id=databricks_client_id,
        databricks_client_secret=databricks_client_secret,
        query=pass2_query
    )

    print(f"Additional matches recovered: {len(df_pass2)}")
    if len(df_pass2) > 0:
        print(f"Time diff stats: min={df_pass2['time_diff_sec'].min()}s, max={df_pass2['time_diff_sec'].max()}s, median={df_pass2['time_diff_sec'].median()}s")
    return df_pass2

def query_enrich(databricks_host: str,
                 databricks_sql_http_path: str,
                 databricks_client_id: str,
                 databricks_client_secret: str,
                    enrich_query: str) -> pd.DataFrame:
    print(f"\n=== Combined Enrichment (single query) ===")
    df_enriched = databricks_query(
        databricks_host=databricks_host,
        databricks_sql_http_path=databricks_sql_http_path,
        databricks_client_id=databricks_client_id,
        databricks_client_secret=databricks_client_secret,
        query=enrich_query
    )
    print(f"Rows returned: {len(df_enriched)}")
    return df_enriched

def add_action_result(df_final: pd.DataFrame,
                      df_audio: pd.DataFrame,
                      partition_filter: str,
                      databricks_host: str,
                      databricks_sql_http_path: str,
                      databricks_client_id: str,
                      databricks_client_secret: str,
                      databricks_calltrace_table: str,
                      databricks_tethys_allaction_table: str,
                      databricks_tethys_actionresult_table: str,
                      databricks_customer_contact_table: str) -> pd.DataFrame:
    
    enrich_query = create_enrich_query(df_final=df_final,
                                      df_audio=df_audio,
                                      PARTITION_FILTER=partition_filter,
                                      databricks_calltrace_table=databricks_calltrace_table,
                                      databricks_tethys_allaction_table=databricks_tethys_allaction_table,
                                      databricks_tethys_actionresult_table=databricks_tethys_actionresult_table,
                                      databricks_customer_contact_table=databricks_customer_contact_table)
    df_enriched = query_enrich(databricks_host=databricks_host,
                               databricks_sql_http_path=databricks_sql_http_path,
                               databricks_client_id=databricks_client_id,
                               databricks_client_secret=databricks_client_secret,
                               enrich_query=enrich_query)
    print(f"\n--- KQHD (Tethys) ---")    
    has_kqhd = df_enriched['kqhd'].notna().sum()
    print(f"Matched: {has_kqhd} ({has_kqhd/len(df_enriched)*100:.1f}%)")
    if has_kqhd > 0:
        print(f"Time diff: median={df_enriched['tethys_time_diff_sec'].dropna().median():.0f}s")
        print(f"Top KQHD codes:")
        print(df_enriched['kqhd'].value_counts().head(10).to_string())
    print(f"\n--- Chính Chủ SĐT ---")
    chinh_chu_count = (df_enriched['is_chinh_chu'] == True).sum()
    bt3_count = (df_enriched['is_chinh_chu'] == False).sum()
    print(f"Chính chủ: {chinh_chu_count} | Bên thứ 3: {bt3_count}")
    print(f"\n--- Queue ---")
    print(f"Has queueid: {df_enriched['queueid'].notna().sum()}")
    queue_583 = (df_enriched['queueid'] == 583).sum()
    print(f"queueid=583 (RB_PRE_GB_UNDER_100K_FROM_6_OVD): {queue_583}")
    
    # Merge enrichments
    df_final = df_final.merge(
        df_enriched[['audio_name', 'kqhd', 'tethys_actiondate', 'tethys_time_diff_sec', 'is_chinh_chu', 'queueid']],
        on='audio_name',
        how='left'
    )
    return df_final

def add_duration_column(df: pd.DataFrame):
    """Add a duration column to the DataFrame based on answertime and closetime.

    Args:
        df (pd.DataFrame): _description_

    Returns:
        _type_: _description_
    """
    if "answertime" not in df.columns or "closetime" not in df.columns:
        return df

    result = df.copy()
    answertime = pd.to_datetime(result["answertime"], errors="coerce")
    closetime = pd.to_datetime(result["closetime"], errors="coerce")
    result["duration"] = (closetime - answertime).dt.total_seconds()
    return result

def combine_passes_and_enrich(df_pass1: pd.DataFrame,
                              df_pass2: pd.DataFrame,
                              df_audio: pd.DataFrame,
                              partition_filter: str,
                              databricks_host: str,
                              databricks_sql_http_path: str,
                              databricks_client_id: str,
                              databricks_client_secret: str,
                              databricks_calltrace_table: str,
                              databricks_tethys_allaction_table: str,
                              databricks_tethys_actionresult_table: str,
                              databricks_customer_contact_table: str) -> pd.DataFrame:
    # --- Combine Pass 1 + Pass 2 ---
    df_pass1_matched = df_pass1[df_pass1['calltraceid'].notna()].copy()
    df_pass1_matched['match_type'] = 'exact'

    df_pass2_matched = df_pass2[['calltraceid', 'customerid', 'audio_name', "rawphone", "raw_queueid", "closedby", "callcodedetails", 'answertime', 'closetime']].copy()
    df_pass2_matched['match_type'] = 'fuzzy'

    # Still unmatched after both passes
    pass2_names = set(df_pass2['audio_name']) if len(df_pass2) > 0 else set()
    still_unmatched_names = set(df_pass1[df_pass1['calltraceid'].isna()]['audio_name']) - pass2_names
    df_still_unmatched = pd.DataFrame({
        'calltraceid': [None] * len(still_unmatched_names),
        'customerid': [None] * len(still_unmatched_names),
        'audio_name': list(still_unmatched_names),
        'match_type': ['unmatched'] * len(still_unmatched_names)
    })

    df_final = pd.concat([df_pass1_matched, df_pass2_matched, df_still_unmatched], ignore_index=True)

    # --- Summary ---
    total = len(df_final)
    exact = len(df_pass1_matched)
    fuzzy = len(df_pass2_matched)
    unmatched = len(df_still_unmatched)
    print(f"=== Combined Pass 1 + Pass 2 ===")
    print(f"Total audio files:  {total}")
    print(f"Exact match:        {exact} ({exact/total*100:.1f}%)")
    print(f"Fuzzy match (±{FUZZY_BUFFER_SECONDS}s):  {fuzzy} ({fuzzy/total*100:.1f}%)")
    print(f"Unmatched:          {unmatched} ({unmatched/total*100:.1f}%)")
    
    df_final = add_action_result(df_final=df_final,
                                 df_audio=df_audio,
                                 partition_filter=partition_filter,
                                 databricks_host=databricks_host,
                                 databricks_sql_http_path=databricks_sql_http_path,
                                 databricks_client_id=databricks_client_id,
                                 databricks_client_secret=databricks_client_secret,
                                 databricks_calltrace_table=databricks_calltrace_table,
                                 databricks_tethys_allaction_table=databricks_tethys_allaction_table,
                                 databricks_tethys_actionresult_table=databricks_tethys_actionresult_table,
                                 databricks_customer_contact_table=databricks_customer_contact_table)
    df_final = add_duration_column(df_final)
    # --- Final Summary ---
    total = len(df_final)
    has_kqhd = df_final['kqhd'].notna().sum()
    null_cif = df_final['customerid'].isna().sum()
    has_cif_no_kqhd = ((df_final['customerid'].notna()) & (df_final['kqhd'].isna())).sum()
    chinh_chu_count = (df_final['is_chinh_chu'] == True).sum()
    bt3_count = (df_final['is_chinh_chu'] == False).sum()
    queue_583 = (df_final['queueid'] == 583).sum()

    print("=== Final Output ===")
    print(f"Total audio files:           {total}")
    print(f"\n--- Calltrace Mapping ---")
    print(f"Exact match:                 {(df_final['match_type']=='exact').sum()}")
    print(f"Fuzzy match:                 {(df_final['match_type']=='fuzzy').sum()}")
    print(f"Unmatched:                   {(df_final['match_type']=='unmatched').sum()}")
    print(f"\n--- KQHD (Tethys) ---")
    print(f"Has KQHD:                    {has_kqhd} ({has_kqhd/total*100:.1f}%)")
    print(f"No KQHD - NULL CIF:          {null_cif} ({null_cif/total*100:.1f}%)")
    print(f"No KQHD - no Tethys action:  {has_cif_no_kqhd} ({has_cif_no_kqhd/total*100:.1f}%)")
    print(f"\n--- Chính Chủ SĐT ---")
    print(f"Chính chủ:                    {chinh_chu_count} ({chinh_chu_count/total*100:.1f}%)")
    print(f"Bên thứ 3:                    {bt3_count} ({bt3_count/total*100:.1f}%)")
    print(f"Unknown (NULL CIF):          {total - chinh_chu_count - bt3_count} ({(total-chinh_chu_count-bt3_count)/total*100:.1f}%)")
    print(f"\n--- Queue ---")
    print(f"Has queueid:                 {df_final['queueid'].notna().sum()}")
    print(f"RB_PRE_GB_UNDER_100K_FROM_6_OVD (583): {queue_583} ({queue_583/total*100:.1f}%)")

    print(f"\nColumns: {list(df_final.columns)}")
    print(df_final.head(5).to_string(index=False))
    return df_final

def get_queueid2queuename(csv_file: str):
    queueid2queuename = {}
    df = pd.read_csv(csv_file, usecols=["queue_id", "queue_name"])
    queueid2queuename = dict(
        zip(
            df["queue_id"].astype(int),
            df["queue_name"].astype(str).str.strip(),
        )
    )
    return queueid2queuename

def seconds_to_mmss(seconds) -> str:
    if seconds is None or pd.isna(seconds):
        return None
    total = int(seconds)
    return f"{total // 60:02}:{total % 60:02}"

def dataframe2metadata(df: pd.DataFrame, queueid2queuename: dict) -> dict:
    """Clean duplicates in the DataFrame based on audio_name, keeping the one with longest duration.

    Args:
        df (pd.DataFrame): DataFrame containing match results with 'audio_name' and 'duration' columns.
        queueid2queuename (dict): Dictionary mapping queueid to queuename.
    Returns:
        dict: Dictionary with cleaned metadata.
    """
    if 'audio_name' not in df.columns or 'duration' not in df.columns:
        return df
    # df_cleaned = df.sort_values(by='duration', ascending=False).drop_duplicates(subset=['audio_name'], keep='first')
    final_metadata = {}
    for idx, row in df.iterrows():
        audio_name = row['audio_name']
        # agent_username = audio_name.split("_")[1]  # assuming agent username is the second part of the filename
        closed_by = "AGENT" if audio_name.split("_")[-2].split(".")[0].upper() == "YES" else "CUSTOMER"
        # if audio_name not in final_metadata:
        # import ipdb; ipdb.set_trace()
        final_metadata[audio_name] = {
            "call_id": str(row["calltraceid"]),
            "customerID": str(row["customerid"]) if pd.notna(row["customerid"]) else None,
            "call_code": str(row["callcodedetails"]) if pd.notna(row["callcodedetails"]) else None,
            "call_date": pd.to_datetime(row["answertime"]).strftime("%Y-%m-%dT%H:%M:%S") if pd.notna(row["answertime"]) else None,
            "agent_username": row["agent_name"] if "agent_name" in row and pd.notna(row["agent_name"]) else None,
            "file_name": audio_name,
            "phone_number": str(row["rawphone"]) if pd.notna(row["rawphone"]) else None,
            "closed_by": closed_by,
            "queueid": str(row["queueid"]) if pd.notna(row["queueid"]) else None,
            "call_duration": seconds_to_mmss(row["duration"]),
            "ovd_days": 100, # mock value,
            "queuename": queueid2queuename.get(int(row["queueid"])) if row["queueid"] else None,
            "is_chinh_chu": row["is_chinh_chu"] if "is_chinh_chu" in row else None,
            "kqhd": row["kqhd"] if "kqhd" in row else None,
            "tethys_actiondate": pd.to_datetime(row["tethys_actiondate"]).strftime("%Y-%m-%dT%H:%M:%S") if "tethys_actiondate" in row and pd.notna(row["tethys_actiondate"]) else None,
            "tethys_time_diff_sec": row["tethys_time_diff_sec"] if "tethys_time_diff_sec" in row else None
            }
    print(f"Final metadata prepared for {len(final_metadata)} audio files.")
    return final_metadata

def get_audio_info(audio_names: list,
                   databricks_host: str,
                   databricks_client_id: str,
                   databricks_client_secret: str,
                   databricks_sql_http_path: str,
                   databricks_calltrace_table: str,
                   databricks_callcode_table: str,
                   databricks_tethys_allaction_table: str,
                   databricks_tethys_actionresult_table: str,
                   databricks_customer_contact_table: str,
                   queueid2queuename_file: str) -> dict:
    
    df_audio, parse_failures = parser_filenames(audio_names)
    df_audio, _ = drop_ambiguous_keys(df_audio)
    real_total = len(df_audio)
    PARTITION_FILTER, AUDIO_CTE, CALLTRACE_CTE, CALLCODE_DETAILS_CTE = create_partition_filter(df_audio=df_audio,
                                                                         calltrace_table=databricks_calltrace_table,
                                                                         callcode_table=databricks_callcode_table)
    
    pass1_query, pass2_query = create_pass_queries(AUDIO_CTE=AUDIO_CTE,
                                                   CALLTRACE_CTE=CALLTRACE_CTE,
                                                   CALLCODE_DETAILS_CTE=CALLCODE_DETAILS_CTE)
    
    df_pass1 = query_pass1(databricks_host=databricks_host,
                           databricks_sql_http_path=databricks_sql_http_path,
                           databricks_client_id=databricks_client_id,
                           databricks_client_secret=databricks_client_secret,
                           pass1_query=pass1_query,
                           real_total=real_total)

    df_pass2 = query_pass2(databricks_host=databricks_host,
                           databricks_sql_http_path=databricks_sql_http_path,
                           databricks_client_id=databricks_client_id,
                           databricks_client_secret=databricks_client_secret,
                           pass2_query=pass2_query)
    # --- Step 4: Summary ---
    df_final = combine_passes_and_enrich(df_pass1=df_pass1,
                                         df_pass2=df_pass2,
                                         df_audio=df_audio,
                                         partition_filter=PARTITION_FILTER,
                                         databricks_host=databricks_host,
                                         databricks_sql_http_path=databricks_sql_http_path,
                                         databricks_client_id=databricks_client_id,
                                         databricks_client_secret=databricks_client_secret,
                                         databricks_calltrace_table=databricks_calltrace_table,
                                         databricks_tethys_allaction_table=databricks_tethys_allaction_table,
                                         databricks_tethys_actionresult_table=databricks_tethys_actionresult_table,
                                         databricks_customer_contact_table=databricks_customer_contact_table)
    queueid2queuename = get_queueid2queuename(queueid2queuename_file)
    file2metadata = dataframe2metadata(df=df_final, queueid2queuename=queueid2queuename)
    return file2metadata
