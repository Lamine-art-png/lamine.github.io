// Legal and policy documents. English is the governing language. These texts
// describe the Academy's implemented data practices; they should be reviewed by
// AGRO-AI's counsel before public launch (see apps/academy/README.md).

const UPDATED = "2026-10-17";

export const LEGAL = {
  terms: {
    title: "Terms of Use",
    updated: UPDATED,
    summary: "The terms that apply when you use AGRO-AI Academy.",
    body: `
These Terms of Use govern your use of AGRO-AI Academy ("the Academy"), the free educational platform operated by AGRO-AI Inc., San Francisco, California ("AGRO-AI", "we"). By creating an account or using the Academy you agree to these terms.

## 1. Free access

All Academy courses, assessments and certificates are provided free of charge. The Academy does not sell subscriptions, paid certificates or course upgrades. Using the Academy does not create, change or require any AGRO-AI software subscription, and Academy accounts are separate from AGRO-AI Enterprise Portal and Platform API accounts.

## 2. Your account

- You must provide accurate information and keep your password confidential.
- You must be at least 16 years old, or have permission from a parent or guardian where local law requires it.
- The name you choose for your credentials must be your real name. Certificates issued under a false identity may be revoked.
- You can delete your account at any time from your account settings.

## 3. Acceptable use

You agree not to:

- share, publish or sell assessment questions or answers, or help others complete assessments on your behalf;
- attempt to obtain a credential through impersonation, automated tools or any other dishonest means;
- interfere with the security or availability of the Academy, probe it for vulnerabilities without authorization, or access other learners' data;
- upload unlawful, harmful or infringing content through feedback, notes or support channels.

## 4. Assessments and credentials

- Assessments are graded on our servers under published passing thresholds (80% for certification exams unless a course states otherwise).
- A certificate confirms that the named learner completed the course requirements and passed its final assessment within AGRO-AI Academy. **It is not an academic degree, a government qualification, or an accredited professional license**, and AGRO-AI Academy is not accredited by any university, government agency or professional certification body.
- Each certificate has a public verification page. We may revoke a certificate issued in error, obtained in breach of these terms, or when you delete your account. Revocation is shown on the verification page.

## 5. Educational content

Course material is provided for education. Agricultural decisions depend on local conditions, regulations and professional judgment. Content about AGRO-AI products describes capabilities as they existed when the material was prepared; product documentation and your agreements with AGRO-AI govern the actual services.

## 6. Intellectual property

Course content, videos, assessments, software and branding belong to AGRO-AI or its licensors. You may use course materials for your personal learning. You may share your own certificate and its verification link freely.

## 7. Availability and changes

We work to keep the Academy available and accurate, but we provide it "as is" without warranties to the extent permitted by law. We may update courses, retire content, or change these terms; material changes will be announced on the Academy before they take effect.

## 8. Liability

To the extent permitted by law, AGRO-AI is not liable for indirect or consequential losses arising from use of the free Academy. Nothing in these terms limits liability that cannot be limited by law.

## 9. Contact

Questions about these terms: [contact@agroai-pilot.com](mailto:contact@agroai-pilot.com).
`,
  },
  privacy: {
    title: "Privacy Policy",
    updated: UPDATED,
    summary: "What AGRO-AI Academy collects, why, and the choices you have.",
    body: `
This policy explains how AGRO-AI Inc. handles personal information in AGRO-AI Academy. It applies only to the Academy; AGRO-AI's commercial products have their own terms.

## What we collect

| Information | Why |
|---|---|
| Email address, display name, password (stored only as a salted PBKDF2 hash) | To create and secure your account |
| Credential name | Printed on your certificates and shown on their public verification pages |
| Optional profile details: country, professional role, organization, bio | To personalize recommendations; country is used in aggregate analytics only if you opt in |
| Language and theme preferences | To show the Academy in your language and chosen appearance |
| Enrollments, lesson progress, notes, bookmarks, quiz and exam answers and scores | To provide courses, resume where you left off, grade assessments and determine certificate eligibility |
| Certificates and their issuance history | To issue and verify credentials |
| Course feedback and support requests | To improve courses and answer your questions |
| Google account identifier and email, if you choose Google sign-in | To sign you in; we never receive your Google password |

We do **not** use advertising trackers, sell personal information, or share learning records with advertisers. We do not store IP addresses in learning analytics.

## Cookies

The Academy uses only cookies needed to run the service: a session cookie (keeps you signed in), a security token cookie (protects forms against cross-site request forgery), and preference cookies for language and theme. There are no third-party analytics or advertising cookies.

## Public verification pages

When a certificate is issued, its verification page shows the credential name, course, issue date, credential ID and status. It does not show your email address, scores or learning history. Anyone with the link or credential ID can view it; this is how employers and others confirm your credential.

## Email

We send essential account and security emails (verification, password reset, security notices) and course emails such as enrollment confirmations, exam results and certificates. Course reminders are off unless you enable them. We do not send marketing campaigns from the Academy. Email is delivered through our provider, Resend.

## Service providers

The Academy runs on Cloudflare (application hosting and database). Email is sent through Resend. These providers process data on our behalf under their data-processing terms.

## Retention and deletion

Your data is kept while your account is active. You can delete your account at any time from **Account → Delete account**. Deletion permanently removes your profile, learning records, notes and assessment answers. Certificates you earned are revoked and anonymized, so their verification pages state that the credential is no longer valid without identifying you. Minimal security audit records (without your profile details) may be retained to protect the integrity of credentials.

You can download a copy of your Academy data from your account settings.

## Your rights

Depending on where you live, you may have rights to access, correct, delete, or restrict processing of your personal information, and to object to processing. Contact us to exercise these rights; we respond within the time required by applicable law.

## Children

The Academy is not directed to children under 16.

## Contact

AGRO-AI Inc., San Francisco, California — [contact@agroai-pilot.com](mailto:contact@agroai-pilot.com).
`,
  },
  accessibility: {
    title: "Accessibility Statement",
    updated: UPDATED,
    summary: "Our commitment to an accessible Academy and how to report barriers.",
    body: `
AGRO-AI Academy is built for learners everywhere — on farms, in classrooms and in offices, on fast connections and slow ones. We aim to conform to the **Web Content Accessibility Guidelines (WCAG) 2.2, level AA**.

## What we have built in

- Semantic HTML with landmarks, headings and a "skip to content" link.
- Full keyboard operation, including the lesson player, notes, and every assessment question type (ordering questions use selectable positions instead of drag and drop).
- Visible focus indicators, color contrast checked in both light and dark themes, and layouts that reflow to 320 pixels wide and 200% zoom.
- Respect for "reduce motion" system settings.
- Captions and transcripts for instructional videos where they are available, and text alternatives for lesson content.
- Language selection across the languages AGRO-AI supports, with right-to-left layouts for Arabic, Persian and Urdu.
- Pages rendered on the server with very little JavaScript, so they work on low-bandwidth connections and older devices.

## Known limitations

- Instructor videos are still in production; lessons currently present the same instruction as text.
- Translations of the interface are machine-prepared and not yet reviewed by native speakers. Course content is available in English first, and certification exams use only reviewed translations.
- The downloadable PDF certificate uses standard fonts that support Latin-script names. For names in other scripts, the web certificate (which can be printed or saved as PDF from your browser) shows your name exactly as written.

## Feedback

If you encounter a barrier, please contact [contact@agroai-pilot.com](mailto:contact@agroai-pilot.com) or use the [contact form](/contact) and choose "Accessibility". We aim to respond within five business days.
`,
  },
};
