---
title: Are Canadian stablecoins being used?
---

```sql cadd_weekly
select activity_week, active_addresses
from marts.weekly_activity
where asset_symbol = 'CADD'
    and not is_pre_launch
    and days_in_week = 7
order by activity_week
```

<LineChart
    data={cadd_weekly}
    x=activity_week
    y=active_addresses
    title="CADD weekly active addresses since launch"
/>
