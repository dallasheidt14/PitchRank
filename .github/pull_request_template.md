# 📦 PitchRank Pull Request

## 🔍 Overview

Provide a clear summary of the change.  

Example:

- Updated rankings UI to use ML-enhanced PowerScore

- Implemented SOS Index (sos_norm)

- Added formatting utilities and tooltips

- Synced frontend types with backend data contract

---

## ✅ Changes Included

### Frontend

- [ ] Updated all PowerScore displays to use `power_score_final`

- [ ] Updated all SOS displays to use `sos_norm`

- [ ] Implemented `formatPowerScore()` (0–100 scale, 2 decimals)

- [ ] Implemented `formatSOSIndex()` (0–100 scale, 1 decimal)

- [ ] Updated RankingsTable

- [ ] Updated TeamHeader

- [ ] Updated ComparePanel

- [ ] Updated HomeLeaderboard & test page

- [ ] Added tooltips ("PowerScore (ML Adjusted)" and "SOS Index")

- [ ] Updated column labels and sorting logic

### Backend / Shared Types

- [ ] Updated `@pitchrank/types` package

- [ ] Verified schema matches `rankings_view` fields

- [ ] Ensured `power_score_final` and `sos_norm` are present

- [ ] Added or reviewed OpenAPI schema

---

## 🧪 Testing Checklist

- [ ] Rankings tables load correctly for all age/gender/state filters

- [ ] Team detail page shows correct PowerScore & SOS Index

- [ ] Sorting by PowerScore works

- [ ] Sorting by SOS Index works

- [ ] No remaining references to `strength_of_schedule`, `power_score`, or `national_power_score`

- [ ] All numbers scale correctly (0–100)

- [ ] Tooltip text renders correctly on desktop/mobile

---

## 📸 Screenshots (If UI Change)

_Add before/after screenshots here._

---

## 📚 Documentation

- [ ] Data Contract updated (if needed)

- [ ] README updated (if needed)

---

## 🚀 Deployment Notes

_Add anything special devops should know (usually none)._

---

## 📎 Related Issues / Tickets

_Example: Closes #187_

---

## 🤝 Reviewer Notes

Anything the reviewer should pay close attention to.

