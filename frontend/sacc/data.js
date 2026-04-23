// SACC — Real data layer (v2.0)
// Sources: renamer_logic.py LOCATION_DATA · Master_Whitelist_v1
// Naming convention: {LOC}-{TYPE}_{YYMMDD}_{identifier-clean}_{CamModel}_{orig_filename}{ext}

// ── Real location whitelist (from renamer_logic.py LOCATION_DATA) ────────────
const SACC_LOCATIONS = {
  "FLM":   { name: "The Florida Mall",                  type: "MALL", region: "Orlando"      },
  "MAM":   { name: "Mall at Millenia",                  type: "MALL", region: "Orlando"      },
  "OFS":   { name: "Orlando Fashion Square",            type: "MALL", region: "Orlando"      },
  "WOM":   { name: "West Oaks Mall",                    type: "MALL", region: "Orlando"      },
  "VLD":   { name: "Vineland Premium Outlets",          type: "NFS",  region: "Orlando"      },
  "IDR":   { name: "International Drive",               type: "NFS",  region: "Orlando"      },
  "LBV":   { name: "Lake Buena Vista",                  type: "NFS",  region: "Orlando"      },
  "WFL":   { name: "Waterford Lakes",                   type: "MALL", region: "Orlando"      },
  "WGN":   { name: "Winter Garden Village",             type: "MALL", region: "Orlando"      },
  "OMP":   { name: "Orlando Marketplace (I-Drive)",     type: "NCS",  region: "Orlando"      },
  "SEM":   { name: "Seminole Towne Center",             type: "MALL", region: "Sanford"      },
  "LKL":   { name: "Lakeland Square Mall",              type: "MALL", region: "Lakeland"     },
  "PDM":   { name: "Paddock Mall",                      type: "MALL", region: "Ocala"        },
  "THL":   { name: "Tallahassee Mall",                  type: "MALL", region: "Tallahassee"  },
  "BRN":   { name: "Brandon Exchange (Brandon Mall)",   type: "MALL", region: "Tampa"        },
  "INP":   { name: "International Plaza",               type: "MALL", region: "Tampa"        },
  "UNM":   { name: "University Mall",                   type: "MALL", region: "Tampa"        },
  "TPA":   { name: "Tampa Premium Outlets",             type: "NFS",  region: "Tampa"        },
  "HVP":   { name: "Hyde Park Village",                 type: "NIKE", region: "Tampa"        },
  "AVE":   { name: "Aventura Mall",                     type: "NIKE", region: "Miami"        },
  "LCN":   { name: "Lincoln Road",                      type: "NIKE", region: "Miami"        },
  "DOL":   { name: "Dolphin Mall",                      type: "NFS",  region: "Miami"        },
  "GVA":   { name: "Gainesville (Celebration Pointe)",  type: "NFS",  region: "Gainesville"  },
  "CEL-K": { name: "Celebration (Kissimmee)",           type: "NFS",  region: "Kissimmee"    },
  "KSM":   { name: "Kissimmee (Osceola Pkwy)",          type: "NCS",  region: "Kissimmee"    },
};

// ── Store type legend ────────────────────────────────────────────────────────
const SACC_TYPE_LABELS = {
  MALL: "Mall",
  NFS:  "Nike Factory Store",
  NCS:  "Nike Clearance Store",
  NIKE: "Nike Flagship",
};

// ── Master Whitelist (from Master_Whitelist_v1, 157 entries — subset shown) ──
// Keyed by style_code for fast SKU lookup
const SACC_WHITELIST = {
  "555088-101": { brand:"Jordan Brand", silhouette:"Air Jordan 1 Retro High OG", colorway_name:"Chicago",              style_code:"555088-101", retail_price:"180", release_date:"2022", new_filename:"AirJordan1RetroHighOg_Chicago.mp4",            notes:"Classic high-top cut." },
  "DZ5485-612": { brand:"Jordan Brand", silhouette:"Air Jordan 1 Retro High OG", colorway_name:"Chicago Lost & Found", style_code:"DZ5485-612", retail_price:"180", release_date:"2022", new_filename:"AirJordan1RetroHighOg_ChicagoLostAndFound.mp4", notes:"Aged aesthetic." },
  "DZ5485-008": { brand:"Jordan Brand", silhouette:"Air Jordan 1 Retro High OG", colorway_name:"Shattered Backboard",  style_code:"DZ5485-008", retail_price:"200", release_date:"2025", new_filename:"AirJordan1RetroHighOg_ShatteredBackboard2025.mp4",notes:"40th Anniversary." },
  "555088-041": { brand:"Jordan Brand", silhouette:"Air Jordan 1 Retro High OG", colorway_name:"Royal Toe",            style_code:"555088-041", retail_price:"170", release_date:"2020", new_filename:"AirJordan1RetroHighOg_RoyalToe.mp4",            notes:"" },
  "CD4487-100": { brand:"Jordan Brand", silhouette:"Air Jordan 1 Retro High OG", colorway_name:"Travis Scott Mocha",  style_code:"CD4487-100", retail_price:"175", release_date:"2019", new_filename:"AirJordan1RetroHighOg_TravisScottMocha.mp4",    notes:"Swoosh reversed." },
  "555088-134": { brand:"Jordan Brand", silhouette:"Air Jordan 1 Retro High OG", colorway_name:"University Blue",     style_code:"555088-134", retail_price:"170", release_date:"2021", new_filename:"AirJordan1RetroHighOg_UniversityBlue.mp4",      notes:"" },
  "DZ5485-042": { brand:"Jordan Brand", silhouette:"Air Jordan 1 Retro High OG", colorway_name:"Royal Reimagined",    style_code:"DZ5485-042", retail_price:"180", release_date:"2023", new_filename:"AirJordan1RetroHighOg_RoyalReimagined.mp4",     notes:"Full suede." },
  "555088-001": { brand:"Jordan Brand", silhouette:"Air Jordan 1 Retro High OG", colorway_name:"Bred / Banned",       style_code:"555088-001", retail_price:"160", release_date:"2016", new_filename:"AirJordan1RetroHighOg_BredBanned.mp4",          notes:"" },
  "DZ5485-701": { brand:"Jordan Brand", silhouette:"Air Jordan 1 Retro High OG", colorway_name:"Yellow Ochre",        style_code:"DZ5485-701", retail_price:"180", release_date:"2024", new_filename:"AirJordan1RetroHighOg_YellowOchre.mp4",         notes:"" },
  "AA3834-100": { brand:"Jordan Brand", silhouette:"Jordan 1 Retro High",         colorway_name:"Virgil Abloh Archive Alaska", style_code:"AA3834-100", retail_price:"230", release_date:"2026", new_filename:"Jordan1RetroHigh_VirgilAblohArchiveAlaska.mp4", notes:"Posthumous archive." },
  "DM7866-202": { brand:"Jordan Brand", silhouette:"Jordan 1 Retro Low OG SP",    colorway_name:"Travis Scott Velvet Brown",   style_code:"DM7866-202", retail_price:"150", release_date:"2024", new_filename:"Jordan1RetroLowOgSp_TravisScottVelvetBrown.mp4",notes:"Cactus Jack collab." },
  "CZ0790-106": { brand:"Jordan Brand", silhouette:"Jordan 1 Retro Low OG",       colorway_name:"Black Toe",           style_code:"CZ0790-106", retail_price:"140", release_date:"2023", new_filename:"Jordan1RetroLowOg_BlackToe.mp4",               notes:"" },
};

// ── Archive entries (filmed at real FL locations) ────────────────────────────
// Naming: {LOC}-{TYPE}_{YYMMDD}_{identifier-clean}_{CamModel}_{orig_filename}{ext}
const SACC_DATA = {
  locations: SACC_LOCATIONS,
  typeLabels: SACC_TYPE_LABELS,
  whitelist:  SACC_WHITELIST,

  sneakers: [
    { id:1,  sku:"555088-101", name:"Air Jordan 1 Retro High OG Chicago",        brand:"Jordan Brand", silhouette:"AJ1 High OG",    colorway:"Chicago",               retail:180, release:"2022-04-09", loc:"FLM", camModel:"iPhone15ProMax", origFile:"raw_footage_01",  ext:".mp4", ts:"0:42",  status:"synced",  rating:5, tags:["retro","og","chicago"]          },
    { id:2,  sku:"DZ5485-612", name:"AJ1 Retro High OG Chicago Lost & Found",   brand:"Jordan Brand", silhouette:"AJ1 High OG",    colorway:"Chicago Lost & Found",  retail:180, release:"2022-11-19", loc:"MAM", camModel:"iPhone14Pro",    origFile:"raw_footage_02",  ext:".mp4", ts:"3:14",  status:"synced",  rating:5, tags:["retro","aged"]                  },
    { id:3,  sku:"555088-041", name:"Air Jordan 1 Retro High OG Royal Toe",     brand:"Jordan Brand", silhouette:"AJ1 High OG",    colorway:"Royal Toe",             retail:170, release:"2020-01-16", loc:"VLD", camModel:"iPhone13Pro",    origFile:"vlookup_raw",     ext:".mp4", ts:"5:40",  status:"synced",  rating:4, tags:["royal","retro"]                },
    { id:4,  sku:"CD4487-100", name:"Air Jordan 1 High OG Travis Scott Mocha",  brand:"Jordan Brand", silhouette:"AJ1 High OG",    colorway:"Travis Scott Mocha",    retail:175, release:"2019-11-30", loc:"MAM", camModel:"iPhone13",       origFile:"ts_mocha_raw",    ext:".mov", ts:"7:22",  status:"pending", rating:5, tags:["travis","collab","reversed"]   },
    { id:5,  sku:"555088-134", name:"Air Jordan 1 Retro High OG University Blue",brand:"Jordan Brand", silhouette:"AJ1 High OG",    colorway:"University Blue",       retail:170, release:"2021-03-06", loc:"WOM", camModel:"iPhone12ProMax", origFile:"unc_blue_raw",    ext:".mp4", ts:"9:04",  status:"error",   rating:4, tags:["unc","university"]             },
    { id:6,  sku:"DZ5485-042", name:"Air Jordan 1 Retro High OG Royal Reimagined",brand:"Jordan Brand",silhouette:"AJ1 High OG",   colorway:"Royal Reimagined",      retail:180, release:"2023-06-17", loc:"INP", camModel:"iPhone15Pro",    origFile:"royal_reimagined",ext:".mp4", ts:"11:30", status:"synced",  rating:4, tags:["suede","royal","reimagined"]   },
    { id:7,  sku:"555088-001", name:"Air Jordan 1 Retro High OG Bred / Banned",  brand:"Jordan Brand", silhouette:"AJ1 High OG",    colorway:"Bred / Banned",         retail:160, release:"2016-09-03", loc:"FLM", camModel:"Cam",            origFile:"bred_banned_raw", ext:".mp4", ts:"13:08", status:"synced",  rating:5, tags:["bred","banned","og"]           },
    { id:8,  sku:"DZ5485-701", name:"Air Jordan 1 Retro High OG Yellow Ochre",  brand:"Jordan Brand", silhouette:"AJ1 High OG",    colorway:"Yellow Ochre",          retail:180, release:"2024-03-23", loc:"HVP", camModel:"iPhone15ProMax", origFile:"yellow_ochre_raw",ext:".mp4", ts:"15:50", status:"pending", rating:3, tags:["ochre","neutral"]               },
    { id:9,  sku:"AA3834-100", name:"Jordan 1 Retro High Virgil Abloh Archive",  brand:"Jordan Brand", silhouette:"AJ1 Retro High", colorway:"Archive Alaska",        retail:230, release:"2026-01-01", loc:"AVE", camModel:"iPhone15ProMax", origFile:"virgil_archive",  ext:".mp4", ts:"17:22", status:"synced",  rating:5, tags:["virgil","archive","collab"]    },
    { id:10, sku:"DM7866-202", name:"Jordan 1 Low OG SP Travis Scott Velvet Brown",brand:"Jordan Brand",silhouette:"AJ1 Low OG SP", colorway:"Travis Scott Velvet Brown",retail:150,release:"2024-06-15",loc:"LCN", camModel:"iPhone14ProMax", origFile:"ts_velvet_raw",   ext:".mov", ts:"19:48", status:"synced",  rating:4, tags:["travis","velvet","cactus jack"]},
    { id:11, sku:"CZ0790-106", name:"Jordan 1 Retro Low OG Black Toe",           brand:"Jordan Brand", silhouette:"AJ1 Low OG",     colorway:"Black Toe",             retail:140, release:"2023-02-18", loc:"TPA", camModel:"iPhone13ProMax", origFile:"black_toe_low",   ext:".mp4", ts:"21:10", status:"synced",  rating:3, tags:["low","black toe"]              },
    { id:12, sku:"DZ5485-008", name:"AJ1 Retro High OG Shattered Backboard 2025",brand:"Jordan Brand", silhouette:"AJ1 High OG",    colorway:"Shattered Backboard",   retail:200, release:"2025-04-05", loc:"FLM", camModel:"iPhone15ProMax", origFile:"sb_40th_raw",     ext:".mp4", ts:"24:15", status:"pending", rating:5, tags:["shattered","40th","anniversary"]},
  ],

  // Import queue — awaiting run_vibe_renamer()
  // preflight: ffprobe metadata used by Pre-Flight Scan to filter before Vortex API
  queue: [
    {
      id:"q1", origFile:"AJ1_chicago_raw_iphone.mov",    size:"3.1 GB", progress:100, status:"done",
      sku:"555088-101", creationTime:"2025-01-11T10:22:00Z", suggestedLoc:"FLM", camModel:"iPhone15ProMax",
      preflight: { sizeBytes:3328*1024*1024, durationSecs:187, fps:60, hasAudio:true,  blackFramePct:1,  motionScore:91, resolution:"4K",   verdict:"pass" }
    },
    {
      id:"q2", origFile:"jordan3_fire_red_4k_shoot.mov", size:"2.4 GB", progress:62,  status:"processing",
      sku:null, creationTime:"2025-01-11T11:04:00Z", suggestedLoc:"MAM", camModel:"iPhone14Pro",
      preflight: { sizeBytes:2458*1024*1024, durationSecs:143, fps:30, hasAudio:true,  blackFramePct:4,  motionScore:78, resolution:"4K",   verdict:"pass" }
    },
    {
      id:"q3", origFile:"unknown_jordan_footage_03.mov", size:"1.9 GB", progress:0,   status:"queued",
      sku:null, creationTime:null, suggestedLoc:null, camModel:null,
      // flag: duration only — black frames and audio absence no longer trigger auto-skip
      preflight: { sizeBytes:1966*1024*1024, durationSecs:2,   fps:30, hasAudio:false, blackFramePct:88, motionScore:3,  resolution:"1080p", verdict:"flag",
        flagReasons:["duration < 3s — clip too short for reliable identification"],
        reviewReasons:["88% black frames — verify coverage, may be partial footage"] }
    },
    {
      id:"q4", origFile:"nb574_grey_day_raw.mp4",        size:"870 MB", progress:0,   status:"queued",
      sku:null, creationTime:null, suggestedLoc:null, camModel:null,
      preflight: { sizeBytes:870*1024*1024,  durationSecs:52,  fps:24, hasAudio:true,  blackFramePct:2,  motionScore:66, resolution:"1080p", verdict:"pass" }
    },
    {
      id:"q5", origFile:"test_clip_blank.mov",           size:"12 MB",  progress:0,   status:"queued",
      sku:null, creationTime:null, suggestedLoc:null, camModel:null,
      // flag: duration + zero motion only — file size and audio absence removed as criteria
      preflight: { sizeBytes:12*1024*1024,   durationSecs:1,   fps:30, hasAudio:false, blackFramePct:99, motionScore:0,  resolution:"720p",  verdict:"flag",
        flagReasons:["duration < 3s — clip too short","motion score 0 — no detectable movement"],
        reviewReasons:["99% black frames — may be lens cap or dead footage"] }
    },
    {
      id:"q6", origFile:"broll_hallway_legacy.mov",      size:"38 MB",  progress:0,   status:"queued",
      sku:null, creationTime:null, suggestedLoc:null, camModel:null,
      // review only: high black frames but valid duration — legacy B-roll, accessible but flagged for human review
      preflight: { sizeBytes:38*1024*1024,   durationSecs:34,  fps:24, hasAudio:false, blackFramePct:61, motionScore:28, resolution:"720p",  verdict:"review",
        reviewReasons:["61% black frames — partial footage, review before API submission"] }
    },
  ],

  // Generator stream log (mirrors Python yield output)
  log: [
    "> [sacc v2.0] init — branch: v2.0-path-integration",
    "> scanning /Volumes/SneakerDrive/Footage/2025/",
    "> ffprobe: found 4 new .mov/.mp4 files",
    "> q1: creation_time=2025-01-11T10:22:00Z · cam=iPhone15ProMax ✓",
    "> q2: creation_time=2025-01-11T11:04:00Z · cam=iPhone14Pro ✓",
    "> q3: creation_time=null — ffprobe fallback → today's date",
    "> Vortex API: q1 matched 555088-101 Chicago (conf. 97%)",
    "> renamer_logic.py: stripping old SACC prefix from q1…",
    "> yield {current:1, total:4, done:false}",
    "> renamed q1 → FLM-MALL_250111_Air-Jordan-1-Chicago_iPhone15ProMax_AJ1_chicago_raw_iphone.mov ✓",
    "> error: q2 — no whitelist match, awaiting manual SKU entry",
    "> yield {current:1, total:4, done:false} — awaiting user input…",
  ],
};

// ── Filename builder (mirrors renamer_logic.py run_vibe_renamer) ─────────────
function buildSACCFilename({ locCode, identifier, camModel, origFile, ext } = {}) {
  const loc = SACC_LOCATIONS[locCode];
  if (!loc || !identifier || !origFile) return null;
  const type = loc.type;
  const identClean = identifier.trim().replace(/\s+/g, '-');
  const cam = (camModel || 'Cam').replace(/\s+/g, '');
  const date = new Date().toISOString().slice(2, 10).replace(/-/g, '');
  return `${locCode}-${type}_${date}_${identClean}_${cam}_${origFile}${ext}`;
}
// Expose globally so Babel-transpiled scripts can access
window.buildSACCFilename = buildSACCFilename;
window.SACC_DATA = SACC_DATA;
window.SACC_LOCATIONS = SACC_LOCATIONS;
