"""Conservative multilingual routing and localized outreach copy.

Explicit per-prospect language preference wins. Otherwise the resolver uses a
single-country market hint and falls back to English for ambiguous/global
records. This prevents confident delivery in the wrong language.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OutreachLanguage(str, Enum):
    auto = "auto"
    en = "en"
    fr = "fr"
    es = "es"
    pt = "pt"
    ar = "ar"


@dataclass(frozen=True, slots=True)
class LanguageResolution:
    language: OutreachLanguage
    source: str
    confidence: str


@dataclass(frozen=True, slots=True)
class LocaleCopy:
    html_lang: str
    direction: str
    individual_greeting: str
    team_greeting: str
    intro: str
    reaching_out: str
    workflow_prefix: str
    launch_message: str
    primary_cta: str
    secondary_prefix: str
    secondary_cta: str
    launch_alt: str
    signoff: str
    founder_title: str
    footer_portal: str
    footer_video: str
    footer_unsubscribe: str
    footer_reason: str
    launch_video_label: str
    subject_water: str
    subject_assets: str
    subject_operations: str


_MARKET_LANGUAGE: dict[str, OutreachLanguage] = {
    # French-first markets
    "france": OutreachLanguage.fr,
    "senegal": OutreachLanguage.fr,
    "sénégal": OutreachLanguage.fr,
    "cote d'ivoire": OutreachLanguage.fr,
    "côte d'ivoire": OutreachLanguage.fr,
    "côte d’ivoire": OutreachLanguage.fr,
    "ivory coast": OutreachLanguage.fr,
    "mali": OutreachLanguage.fr,
    "burkina faso": OutreachLanguage.fr,
    "benin": OutreachLanguage.fr,
    "bénin": OutreachLanguage.fr,
    "togo": OutreachLanguage.fr,
    "cameroon": OutreachLanguage.fr,
    "cameroun": OutreachLanguage.fr,
    "madagascar": OutreachLanguage.fr,
    "morocco": OutreachLanguage.fr,
    "maroc": OutreachLanguage.fr,
    "tunisia": OutreachLanguage.fr,
    "tunisie": OutreachLanguage.fr,
    # Spanish-first markets
    "spain": OutreachLanguage.es,
    "españa": OutreachLanguage.es,
    "mexico": OutreachLanguage.es,
    "méxico": OutreachLanguage.es,
    "peru": OutreachLanguage.es,
    "perú": OutreachLanguage.es,
    "chile": OutreachLanguage.es,
    "argentina": OutreachLanguage.es,
    "colombia": OutreachLanguage.es,
    "ecuador": OutreachLanguage.es,
    "bolivia": OutreachLanguage.es,
    "paraguay": OutreachLanguage.es,
    "uruguay": OutreachLanguage.es,
    "guatemala": OutreachLanguage.es,
    "honduras": OutreachLanguage.es,
    "el salvador": OutreachLanguage.es,
    "costa rica": OutreachLanguage.es,
    "panama": OutreachLanguage.es,
    "panamá": OutreachLanguage.es,
    "dominican republic": OutreachLanguage.es,
    "república dominicana": OutreachLanguage.es,
    # Portuguese-first markets
    "brazil": OutreachLanguage.pt,
    "brasil": OutreachLanguage.pt,
    "portugal": OutreachLanguage.pt,
    "angola": OutreachLanguage.pt,
    "mozambique": OutreachLanguage.pt,
    "moçambique": OutreachLanguage.pt,
    # Arabic-first markets
    "saudi arabia": OutreachLanguage.ar,
    "united arab emirates": OutreachLanguage.ar,
    "uae": OutreachLanguage.ar,
    "qatar": OutreachLanguage.ar,
    "kuwait": OutreachLanguage.ar,
    "bahrain": OutreachLanguage.ar,
    "oman": OutreachLanguage.ar,
    "jordan": OutreachLanguage.ar,
    "egypt": OutreachLanguage.ar,
}


def resolve_language(preferred: OutreachLanguage, country: str) -> LanguageResolution:
    if preferred != OutreachLanguage.auto:
        return LanguageResolution(preferred, "explicit_preference", "high")
    normalized = " ".join(country.strip().lower().replace("–", "-").split())
    if not normalized:
        return LanguageResolution(OutreachLanguage.en, "default_no_country", "low")
    if any(marker in normalized for marker in (" / ", "global", "multiple", ",")):
        return LanguageResolution(OutreachLanguage.en, "ambiguous_multimarket_default", "low")
    language = _MARKET_LANGUAGE.get(normalized)
    if language is not None:
        return LanguageResolution(language, "country_market", "medium")
    return LanguageResolution(OutreachLanguage.en, "default_market", "low")


_LOCALES: dict[OutreachLanguage, LocaleCopy] = {
    OutreachLanguage.en: LocaleCopy(
        html_lang="en", direction="ltr",
        individual_greeting="Hi {first_name},", team_greeting="Hello {account} team,",
        intro="I’m Lamine Dabo, Founder & CEO of AGRO-AI.",
        reaching_out="I’m reaching out because {observation}{relevance}",
        workflow_prefix="For {account}, the first workflow I would examine is:",
        launch_message="We launched the AGRO-AI Enterprise Portal globally this week. You can create an account and start using it directly—no sales call required.",
        primary_cta="Get started with AGRO-AI", secondary_prefix="Prefer to talk first?",
        secondary_cta="Book 30 minutes with me", launch_alt="AGRO-AI Enterprise Portal global launch",
        signoff="Best,", founder_title="Founder & CEO · AGRO-AI",
        footer_portal="Enterprise Portal", footer_video="Launch video", footer_unsubscribe="Unsubscribe",
        footer_reason="You received this message because this organization or professional role appears relevant to the operational problem described above.",
        launch_video_label="Launch video:", subject_water="A practical workflow idea for {account}",
        subject_assets="Operating intelligence across {account}'s agricultural assets",
        subject_operations="A working idea for {account}'s agricultural operations",
    ),
    OutreachLanguage.fr: LocaleCopy(
        html_lang="fr", direction="ltr",
        individual_greeting="Bonjour {first_name},", team_greeting="Bonjour à l’équipe {account},",
        intro="Je suis Lamine Dabo, fondateur et PDG d’AGRO-AI.",
        reaching_out="Je vous contacte parce que {observation}{relevance}",
        workflow_prefix="Pour {account}, le premier flux de travail que j’examinerais est le suivant :",
        launch_message="Nous avons lancé cette semaine le portail d’entreprise AGRO-AI à l’échelle mondiale. Vous pouvez créer un compte et commencer à l’utiliser directement, sans appel commercial préalable.",
        primary_cta="Commencer avec AGRO-AI", secondary_prefix="Vous préférez en parler d’abord ?",
        secondary_cta="Réserver 30 minutes avec moi", launch_alt="Lancement mondial du portail d’entreprise AGRO-AI",
        signoff="Bien à vous,", founder_title="Fondateur & PDG · AGRO-AI",
        footer_portal="Portail d’entreprise", footer_video="Vidéo de lancement", footer_unsubscribe="Se désabonner",
        footer_reason="Vous recevez ce message parce que cette organisation ou ce rôle professionnel semble directement concerné par le problème opérationnel décrit ci-dessus.",
        launch_video_label="Vidéo de lancement :", subject_water="Une idée de flux de travail concret pour {account}",
        subject_assets="Intelligence opérationnelle pour les actifs agricoles de {account}",
        subject_operations="Une idée concrète pour les opérations agricoles de {account}",
    ),
    OutreachLanguage.es: LocaleCopy(
        html_lang="es", direction="ltr",
        individual_greeting="Hola {first_name},", team_greeting="Hola, equipo de {account}:",
        intro="Soy Lamine Dabo, fundador y CEO de AGRO-AI.",
        reaching_out="Me pongo en contacto porque {observation}{relevance}",
        workflow_prefix="Para {account}, el primer flujo de trabajo que analizaría es:",
        launch_message="Esta semana lanzamos globalmente el Portal Empresarial de AGRO-AI. Puede crear una cuenta y empezar a utilizarlo directamente, sin necesidad de una llamada comercial previa.",
        primary_cta="Empezar con AGRO-AI", secondary_prefix="¿Prefiere hablar primero?",
        secondary_cta="Reserve 30 minutos conmigo", launch_alt="Lanzamiento global del Portal Empresarial de AGRO-AI",
        signoff="Un saludo,", founder_title="Fundador y CEO · AGRO-AI",
        footer_portal="Portal Empresarial", footer_video="Vídeo de lanzamiento", footer_unsubscribe="Darse de baja",
        footer_reason="Ha recibido este mensaje porque esta organización o función profesional parece directamente relacionada con el problema operativo descrito anteriormente.",
        launch_video_label="Vídeo de lanzamiento:", subject_water="Una idea práctica de flujo de trabajo para {account}",
        subject_assets="Inteligencia operativa para los activos agrícolas de {account}",
        subject_operations="Una idea práctica para las operaciones agrícolas de {account}",
    ),
    OutreachLanguage.pt: LocaleCopy(
        html_lang="pt-BR", direction="ltr",
        individual_greeting="Olá {first_name},", team_greeting="Olá, equipe da {account},",
        intro="Sou Lamine Dabo, fundador e CEO da AGRO-AI.",
        reaching_out="Estou entrando em contato porque {observation}{relevance}",
        workflow_prefix="Para a {account}, o primeiro fluxo de trabalho que eu analisaria é:",
        launch_message="Lançamos globalmente esta semana o Portal Empresarial da AGRO-AI. É possível criar uma conta e começar a usar a plataforma diretamente, sem necessidade de uma chamada comercial prévia.",
        primary_cta="Começar com a AGRO-AI", secondary_prefix="Prefere conversar primeiro?",
        secondary_cta="Agende 30 minutos comigo", launch_alt="Lançamento global do Portal Empresarial da AGRO-AI",
        signoff="Atenciosamente,", founder_title="Fundador e CEO · AGRO-AI",
        footer_portal="Portal Empresarial", footer_video="Vídeo de lançamento", footer_unsubscribe="Cancelar inscrição",
        footer_reason="Você recebeu esta mensagem porque esta organização ou função profissional parece diretamente relacionada ao problema operacional descrito acima.",
        launch_video_label="Vídeo de lançamento:", subject_water="Uma ideia prática de fluxo de trabalho para a {account}",
        subject_assets="Inteligência operacional para os ativos agrícolas da {account}",
        subject_operations="Uma ideia prática para as operações agrícolas da {account}",
    ),
    OutreachLanguage.ar: LocaleCopy(
        html_lang="ar", direction="rtl",
        individual_greeting="مرحبًا {first_name}،", team_greeting="مرحبًا بفريق {account}،",
        intro="أنا لامين دابو، المؤسس والرئيس التنفيذي لشركة AGRO-AI.",
        reaching_out="أتواصل معكم لأن {observation}{relevance}",
        workflow_prefix="بالنسبة إلى {account}، فإن أول سير عمل أقترح دراسته هو:",
        launch_message="أطلقنا هذا الأسبوع بوابة AGRO-AI للمؤسسات عالميًا. يمكنكم إنشاء حساب والبدء في استخدام المنصة مباشرة، من دون الحاجة إلى مكالمة مبيعات مسبقة.",
        primary_cta="ابدأ الآن مع AGRO-AI", secondary_prefix="تفضلون التحدث أولًا؟",
        secondary_cta="احجزوا 30 دقيقة معي", launch_alt="الإطلاق العالمي لبوابة AGRO-AI للمؤسسات",
        signoff="مع خالص التحية،", founder_title="المؤسس والرئيس التنفيذي · AGRO-AI",
        footer_portal="بوابة المؤسسات", footer_video="فيديو الإطلاق", footer_unsubscribe="إلغاء الاشتراك",
        footer_reason="تلقيتم هذه الرسالة لأن هذه المؤسسة أو هذه المسؤولية المهنية تبدو مرتبطة مباشرة بالتحدي التشغيلي الموضح أعلاه.",
        launch_video_label="فيديو الإطلاق:", subject_water="فكرة عملية لسير عمل لدى {account}",
        subject_assets="ذكاء تشغيلي للأصول الزراعية لدى {account}",
        subject_operations="فكرة عملية للعمليات الزراعية لدى {account}",
    ),
}


def locale_for(language: OutreachLanguage) -> LocaleCopy:
    return _LOCALES[OutreachLanguage.en if language == OutreachLanguage.auto else language]


def segment_copy(language: OutreachLanguage, segment: str) -> tuple[str, str]:
    lower = segment.lower()
    if "water" in lower or "district" in lower or "agency" in lower:
        key = "water"
    elif "institutional" in lower or "asset manager" in lower or "farmland" in lower:
        key = "assets"
    elif "channel" in lower or "ecosystem" in lower:
        key = "channel"
    else:
        key = "operations"

    copies: dict[OutreachLanguage, dict[str, tuple[str, str]]] = {
        OutreachLanguage.en: {
            "water": ("We built AGRO-AI for agricultural and water-related workflows where evidence is often spread across field systems, irrigation data, ET and weather sources, reports, uploaded documents, email, and internal operating records.", "The portal brings that evidence into one working environment so teams can investigate exceptions, organize supporting sources, assign follow-up actions, and preserve a traceable decision record."),
            "assets": ("We built AGRO-AI for agricultural portfolios where operating evidence remains fragmented across farms, managers, irrigation platforms, equipment systems, weather and ET sources, spreadsheets, files, and local workflows.", "The portal gives teams a common operating layer for material exceptions, water and field-risk evidence, planned-versus-completed activity, unresolved actions, and portfolio-level patterns without removing local operating autonomy."),
            "channel": ("We built AGRO-AI as an intelligence and workflow layer above the agricultural systems organizations already use, rather than another rip-and-replace platform.", "That creates a practical route to extend existing technology and member relationships into connected evidence, operational exceptions, assigned work, and traceable decisions."),
            "operations": ("We built AGRO-AI for agricultural teams that already operate across multiple systems—field and machine platforms, irrigation infrastructure, ET and weather data, cloud files, reports, email, and internal operating records.", "The portal creates one intelligence and workflow layer across those sources so teams can see exceptions earlier, turn decisions into assigned work, compare planned versus completed activity, and preserve a traceable record of what happened and what was verified."),
        },
        OutreachLanguage.fr: {
            "water": ("Nous avons conçu AGRO-AI pour les flux de travail agricoles et liés à l’eau, où les preuves sont souvent dispersées entre systèmes de terrain, données d’irrigation, sources ET et météo, rapports, documents téléversés, e-mails et dossiers opérationnels internes.", "Le portail rassemble ces éléments dans un même environnement de travail afin d’analyser les exceptions, structurer les sources justificatives, attribuer les actions de suivi et conserver une trace claire des décisions."),
            "assets": ("Nous avons conçu AGRO-AI pour les portefeuilles agricoles où les preuves opérationnelles restent fragmentées entre exploitations, gestionnaires, plateformes d’irrigation, équipements, sources météo et ET, feuilles de calcul, fichiers et processus locaux.", "Le portail offre une couche opérationnelle commune pour suivre les exceptions importantes, les risques liés à l’eau et au terrain, les activités prévues et réalisées, les actions non résolues et les tendances à l’échelle du portefeuille, sans supprimer l’autonomie locale."),
            "channel": ("Nous avons conçu AGRO-AI comme une couche d’intelligence et de workflow au-dessus des systèmes agricoles déjà utilisés, plutôt que comme une plateforme supplémentaire imposant de tout remplacer.", "Cela permet d’étendre concrètement la valeur des technologies et réseaux existants vers des preuves connectées, des exceptions opérationnelles, des actions assignées et des décisions traçables."),
            "operations": ("Nous avons conçu AGRO-AI pour les équipes agricoles qui travaillent déjà avec plusieurs systèmes : plateformes terrain et machines, infrastructures d’irrigation, données ET et météo, fichiers cloud, rapports, e-mails et dossiers opérationnels internes.", "Le portail crée une couche unique d’intelligence et de workflow afin de détecter plus tôt les exceptions, transformer les décisions en actions assignées, comparer le prévu au réalisé et conserver une trace vérifiable de ce qui s’est passé."),
        },
        OutreachLanguage.es: {
            "water": ("Creamos AGRO-AI para flujos de trabajo agrícolas y relacionados con el agua, donde la evidencia suele estar dispersa entre sistemas de campo, datos de riego, fuentes de ET y clima, informes, documentos cargados, correo electrónico y registros operativos internos.", "El portal reúne esa evidencia en un único entorno de trabajo para investigar excepciones, organizar fuentes de respaldo, asignar acciones de seguimiento y conservar un registro trazable de las decisiones."),
            "assets": ("Creamos AGRO-AI para carteras agrícolas donde la evidencia operativa permanece fragmentada entre fincas, gestores, plataformas de riego, sistemas de maquinaria, fuentes meteorológicas y de ET, hojas de cálculo, archivos y procesos locales.", "El portal ofrece una capa operativa común para excepciones relevantes, evidencia de riesgos hídricos y de campo, actividad planificada frente a ejecutada, acciones pendientes y patrones a nivel de cartera, sin eliminar la autonomía operativa local."),
            "channel": ("Creamos AGRO-AI como una capa de inteligencia y flujo de trabajo por encima de los sistemas agrícolas que las organizaciones ya utilizan, no como otra plataforma que obliga a sustituirlo todo.", "Esto permite ampliar de forma práctica el valor de la tecnología y las relaciones existentes hacia evidencia conectada, excepciones operativas, trabajo asignado y decisiones trazables."),
            "operations": ("Creamos AGRO-AI para equipos agrícolas que ya trabajan con múltiples sistemas: plataformas de campo y maquinaria, infraestructura de riego, datos de ET y clima, archivos en la nube, informes, correo electrónico y registros operativos internos.", "El portal crea una única capa de inteligencia y flujo de trabajo para detectar excepciones antes, convertir decisiones en trabajo asignado, comparar lo planificado con lo ejecutado y conservar un registro trazable de lo ocurrido y verificado."),
        },
        OutreachLanguage.pt: {
            "water": ("Criamos a AGRO-AI para fluxos de trabalho agrícolas e relacionados à água, nos quais as evidências costumam ficar dispersas entre sistemas de campo, dados de irrigação, fontes de ET e clima, relatórios, documentos enviados, e-mails e registros operacionais internos.", "O portal reúne essas evidências em um único ambiente de trabalho para investigar exceções, organizar fontes de suporte, atribuir ações de acompanhamento e manter um registro rastreável das decisões."),
            "assets": ("Criamos a AGRO-AI para portfólios agrícolas nos quais as evidências operacionais permanecem fragmentadas entre fazendas, gestores, plataformas de irrigação, sistemas de equipamentos, fontes meteorológicas e de ET, planilhas, arquivos e processos locais.", "O portal oferece uma camada operacional comum para exceções relevantes, evidências de risco hídrico e de campo, atividade planejada versus executada, ações pendentes e padrões de portfólio, sem retirar a autonomia operacional local."),
            "channel": ("Criamos a AGRO-AI como uma camada de inteligência e fluxo de trabalho sobre os sistemas agrícolas que as organizações já utilizam, e não como outra plataforma que exige substituir tudo.", "Isso cria uma forma prática de ampliar o valor da tecnologia e das relações existentes para evidências conectadas, exceções operacionais, trabalho atribuído e decisões rastreáveis."),
            "operations": ("Criamos a AGRO-AI para equipes agrícolas que já operam com vários sistemas: plataformas de campo e máquinas, infraestrutura de irrigação, dados de ET e clima, arquivos em nuvem, relatórios, e-mails e registros operacionais internos.", "O portal cria uma única camada de inteligência e fluxo de trabalho para identificar exceções mais cedo, transformar decisões em trabalho atribuído, comparar o planejado com o executado e manter um registro rastreável do que aconteceu e foi verificado."),
        },
        OutreachLanguage.ar: {
            "water": ("صممنا AGRO-AI لسير العمل الزراعي والمرتبط بالمياه، حيث تكون الأدلة غالبًا موزعة بين أنظمة الحقول وبيانات الري ومصادر التبخر والنتح والطقس والتقارير والوثائق المرفوعة والبريد الإلكتروني والسجلات التشغيلية الداخلية.", "تجمع البوابة هذه الأدلة في بيئة عمل واحدة لتمكين الفرق من تحليل الاستثناءات وتنظيم المصادر الداعمة وتكليف إجراءات المتابعة والاحتفاظ بسجل واضح للقرارات."),
            "assets": ("صممنا AGRO-AI للمحافظ الزراعية التي تبقى فيها الأدلة التشغيلية موزعة بين المزارع والمديرين ومنصات الري وأنظمة المعدات ومصادر الطقس والتبخر والنتح وجداول البيانات والملفات وسير العمل المحلي.", "توفر البوابة طبقة تشغيلية مشتركة لمتابعة الاستثناءات المهمة وأدلة مخاطر المياه والحقول والنشاط المخطط مقابل المنفذ والإجراءات المعلقة والأنماط على مستوى المحفظة، مع الحفاظ على الاستقلالية التشغيلية المحلية."),
            "channel": ("صممنا AGRO-AI كطبقة ذكاء وسير عمل فوق الأنظمة الزراعية التي تستخدمها المؤسسات بالفعل، وليس كمنصة أخرى تفرض استبدال كل شيء.", "يتيح ذلك توسيع قيمة التقنيات والعلاقات القائمة نحو أدلة مترابطة واستثناءات تشغيلية وأعمال مكلفة وقرارات قابلة للتتبع."),
            "operations": ("صممنا AGRO-AI للفرق الزراعية التي تعمل بالفعل عبر أنظمة متعددة، بما في ذلك منصات الحقول والآلات والبنية التحتية للري وبيانات التبخر والنتح والطقس والملفات السحابية والتقارير والبريد الإلكتروني والسجلات التشغيلية الداخلية.", "تنشئ البوابة طبقة موحدة للذكاء وسير العمل تساعد الفرق على اكتشاف الاستثناءات مبكرًا وتحويل القرارات إلى أعمال مكلفة ومقارنة المخطط بالمنفذ والاحتفاظ بسجل قابل للتتبع لما حدث وما تم التحقق منه."),
        },
    }
    return copies[language][key]


__all__ = ["LanguageResolution", "LocaleCopy", "OutreachLanguage", "locale_for", "resolve_language", "segment_copy"]
