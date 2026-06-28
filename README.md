# \# WorkTracker Bot

# 

# A private Discord bot for tracking work hours across a team. Built with Python, hosted on Render, and powered by Supabase.

# 

# \---

# 

# \## Features

# \- Clock in and out with slash commands

# \- Mandatory work description on every clock-out

# \- Automatic status updates posted to a dedicated Discord channel

# \- Personal and server-wide reports with bar charts

# \- Monthly reset with permanent session archiving

# \- All times displayed in IST (Indian Standard Time)

# 

# \---

# 

# \## Commands

# 

# \### Daily

# | Command | Description |

# |---|---|

# | /clockin | Start your work session |

# | /clockout | End your session and submit a work description |

# 

# \### Personal Reports (private — only you can see)

# | Command | Description |

# |---|---|

# | /mystats | Quick summary of your last 5 sessions |

# | /myreport | Full report with monthly breakdown |

# | /lifetimehours | Your total hours worked since day one |

# 

# \### Team

# | Command | Description |

# |---|---|

# | /teamstatus | See who is currently clocked in |

# | /serverreport | Full team leaderboard with bar chart |

# 

# \### Editing

# | Command | Description |

# |---|---|

# | /editsessions | View your last 10 sessions with numbers |

# | /edittime | Fix a wrong clock-in or clock-out time |

# 

# \### Admin Only

# | Command | Description |

# |---|---|

# | /viewlog | Live database summary |

# | /resetmonth | Archive this month and clear the live log |

# 

# \---

# 

# \## Tech Stack

# \- Python 3.14

# \- discord.py

# \- Supabase (PostgreSQL database)

# \- Render (bot hosting)

# \- UptimeRobot (keep-alive monitoring)

# 

# \---

# 

# \## Setup Guide

# 

# \### 1. Discord Developer Portal

# \- Go to https://discord.com/developers/applications

# \- Create a new application and add a bot

# \- Enable Server Members Intent and Message Content Intent

# \- Generate an invite URL with bot scope and permissions: Send Messages, Read Message History, Use Slash Commands, Embed Links, Attach Files

# \- Invite the bot to your server

# 

# \### 2. Supabase

# \- Create a free project at https://supabase.com

# \- Run this in the SQL Editor to create the three required tables:

# 

# ```sql

# create table active\_sessions (

# &#x20;   user\_id text primary key,

# &#x20;   username text not null,

# &#x20;   clock\_in timestamptz not null

# );

# 

# create table completed\_sessions (

# &#x20;   id bigserial primary key,

# &#x20;   user\_id text not null,

# &#x20;   username text not null,

# &#x20;   clock\_in timestamptz not null,

# &#x20;   clock\_out timestamptz not null,

# &#x20;   duration\_seconds integer not null,

# &#x20;   description text not null,

# &#x20;   month\_key text not null

# );

# 

# create table archived\_sessions (

# &#x20;   id bigserial primary key,

# &#x20;   user\_id text not null,

# &#x20;   username text not null,

# &#x20;   clock\_in timestamptz not null,

# &#x20;   clock\_out timestamptz not null,

# &#x20;   duration\_seconds integer not null,

# &#x20;   description text not null,

# &#x20;   month\_key text not null,

# &#x20;   archived\_at timestamptz default now()

# );

# ```

# 

# \- Go to Project Settings → API and copy your Project URL and anon public key

# 

# \### 3. Render

# \- Go to https://render.com and create a new Web Service

# \- Connect your GitHub repository

# \- Set the start command to `python bot.py`

# \- Add these environment variables:

# 

# | Variable | Value |

# |---|---|

# | TOKEN | Your Discord bot token |

# | STATUS\_CHANNEL\_ID | Your status channel ID |

# | SUPABASE\_URL | Your Supabase project URL |

# | SUPABASE\_KEY | Your Supabase anon public key |

# | ADMIN\_IDS | Discord user IDs of admins, comma separated |

# 

# \### 4. UptimeRobot

# \- Create a free account at https://uptimerobot.com

# \- Add a new HTTP(s) monitor pointing to your Render URL

# \- Set the interval to every 10 minutes

# \- This keeps Render awake and prevents Supabase from pausing

# 

# \---

# 

# \## Important Notes

# \- Supabase free tier pauses after 7 days of inactivity — UptimeRobot prevents this by keeping the bot active

# \- Render free tier spins down without traffic — UptimeRobot prevents this too

# \- If the bot goes offline, check Supabase first (restore if paused), then check Render logs

# \- All timestamps are stored in UTC internally and displayed in IST

# \- Run /serverreport before /resetmonth every month to save a record of the team's hours

