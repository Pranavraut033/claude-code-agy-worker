#!/usr/bin/env python3
"""Generate seed/ (git repo with tickets/) plus checks/labels.json (hidden). stdlib only, seeded."""
import json, os, random, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); SEED = os.path.join(HERE, "seed")
T = [  # (category, urgency, text)
("billing",3,"My card was charged $480 twice this morning for the annual plan. I only signed up once, and the second charge has already emptied my checking account buffer. Rent is due tomorrow. Please reverse the duplicate today, I cannot wait a week for a refund cycle."),
("billing",2,"Our finance team needs invoices for the last four months with our VAT number on them. The ones in the dashboard show the old company name. We close the quarter on Friday, so we would like the corrected PDFs before then if that is possible."),
("billing",1,"Just curious whether you offer a discount if we pay annually instead of monthly. We are happy with the product and nothing is wrong. No rush at all, answer whenever you get a chance."),
("billing",3,"I cancelled in March and got the confirmation email, but a charge just appeared again on my statement for $79. This is the third month in a row. If it is not refunded and stopped immediately I will dispute it with my bank."),
("billing",2,"The coupon code SPRING20 was rejected at checkout though the newsletter said it works until the 30th. I would like to upgrade today to use it. Can someone check why it fails? I will probably buy tomorrow either way."),
("billing",1,"Small thing: the receipt email lists my address as Main Street but I live on Main Avenue. It does not affect anything I think, though I would tidy it up when convenient."),
("bug",3,"Since the update an hour ago every save in the editor wipes the document and shows a blank page. I lost two hours of work and my whole team is seeing the same thing. We have a client presentation at noon and cannot open our files at all."),
("bug",2,"The export to CSV drops the last row whenever the table has more than 1000 entries. I noticed while reconciling numbers. As a workaround I split the table in half, but that is tedious and I worry someone else will miss it."),
("bug",1,"The tooltip on the settings gear overlaps the label by a couple pixels in Firefox. It is purely cosmetic. Mentioning it in case you are tidying CSS someday."),
("bug",3,"Anyone can see other customers' project names in the sidebar after logging in with my account. I refreshed and the list changed to a different company's projects. This looks like a data leak and I think you should look at it right now."),
("bug",2,"Dark mode resets itself to light each time I reopen the mobile app, and push notifications arrive about ten minutes late. The app is still usable for me. It started after the last release, if that helps narrow it down."),
("bug",1,"Typo on the pricing page: 'recieve' in the third bullet under the Team plan. Thought you would want to know. Everything else looks great."),
("feature",2,"We are rolling out your tool to 300 staff next month and need single sign-on with Okta. Without it our security office will not approve the rollout. Is it on your roadmap, and can you give a date?"),
("feature",1,"It would be nice to have keyboard shortcuts for switching between boards. I use the product all day and the mouse trips get old. Not urgent, just an idea from a power user."),
("feature",1,"Could you add an option to change the default font in reports? The grey sans looks a little dull compared to our brand. Happy to wait for a future release."),
("feature",2,"Our auditors require an immutable log of who changed permissions, with export. The current activity feed is not enough. We have an audit window beginning in three weeks and would need something by then."),
("feature",1,"Wishing for a way to pin favourite dashboards to the top. I currently scroll past forty of them. Entirely optional, I know you have bigger things going on."),
("feature",3,"Our biggest customer's contract renewal depends on bulk import by the end of this week. We have lost them if the importer cannot take their 50k-row file. Please tell me if any beta of it exists that we can use today."),
("account",3,"I cannot log in and the reset email never arrives. Worse, I got a login alert from another country an hour ago and I think someone has taken over my account. I need it locked and recovered urgently, there is client data in there."),
("account",2,"I changed jobs and need to move our team's workspace ownership from Dana to me, since Dana left the company. Dana's email is deactivated so she cannot approve. We can still work but can't add new seats until this is resolved."),
("account",1,"How do I change the display name shown on my profile? I looked through settings and could not find the field. Thank you in advance, no hurry."),
("account",2,"Two-factor codes from my authenticator app are always rejected since I got a new phone. I have the backup codes but they say 'already used'. I am locked out of the admin console which I need for payroll on Thursday."),
("account",1,"Please delete the old test account created under my email last year when I trialled the product. There is no data in it. Whenever your team has a moment."),
("other",1,"Hi, I run a podcast about small-business tools and would love to interview someone from your team. We reach roughly five thousand listeners. Let me know if that is of interest."),
("other",2,"I am a journalist writing a piece for Friday about your recent outage and need a comment from your press office on what caused it. Could someone reach me by Thursday afternoon?"),
("other",1,"Where can I find your brand logo files? I am writing a blog post comparing project tools and want to use the correct image. No deadline."),
("other",3,"This is the security researcher who emailed last week. I have found an unauthenticated endpoint exposing user emails and I plan to publish in 48 hours unless I hear back from someone with authority. Please route this to your security lead immediately."),
("other",1,"Thanks to whoever helped me last month, the new onboarding video was very clear. My colleague asked if the training webinars are recorded. That is all, have a lovely week."),
("other",2,"We are a university considering a partnership for student licences. Our procurement committee meets in ten days and would like a one-page overview and a contact for legal terms before then."),
("billing",2,"Could you resend the receipt for the October payment? Our expenses system rejected the previous one because it lacked a transaction number. Reimbursement is due by next Monday."),
]
assert len(T) == 30, len(T)
r = random.Random(7); idx = list(range(30)); r.shuffle(idx)
os.makedirs(os.path.join(SEED, "tickets"), exist_ok=True); labels = {}
for n, i in enumerate(idx):
    c, u, t = T[i]; name = "ticket_%02d.txt" % n
    open(os.path.join(SEED, "tickets", name), "w").write(t + "\n"); labels[name] = {"category": c, "urgency": u}
open(os.path.join(HERE, "checks", "labels.json"), "w").write(json.dumps(labels, indent=1))
open(os.path.join(SEED, ".gitignore"), "w").write("__pycache__/\n")
subprocess.run("git init -q && git add -A && git -c user.name=bench -c user.email=bench@local commit -qm seed", shell=True, cwd=SEED, check=True)
