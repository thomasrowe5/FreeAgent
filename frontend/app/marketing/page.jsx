"use client";

/**
 * MarketingBuilder renders a lightweight landing page and email campaign builder
 * for FreeAgent teams. The page lets teams edit hero/services/testimonial content,
 * design outbound emails via drag-and-drop blocks, and generate tone profiles
 * that feed into proposal and follow-up agents.
 */

import { useEffect, useMemo, useState } from "react";
import { supabase } from "@/lib/supabase";
import { postJSON } from "@/lib/api";

const defaultHero = {
  title: "Supercharge Client Workflows",
  subtitle: "FreeAgent automates lead follow-ups, proposals, and onboarding in minutes.",
  ctaText: "Start My Automation",
  illustration: "https://placehold.co/600x360?text=FreeAgent",
};

const defaultServices = [
  { title: "Lead Capture", description: "Convert inbound conversations into prioritized opportunities." },
  { title: "Proposal Drafts", description: "Generate branded proposals aligned with each client’s tone." },
  { title: "Follow-up Intelligence", description: "Schedule nudges, track sentiment, and close faster." },
];

const defaultTestimonials = [
  {
    name: "Jordan Miles",
    role: "Founder, Orbit Labs",
    quote: "We cut sales ops time by 60% with FreeAgent’s automation.",
  },
  {
    name: "Sasha Lee",
    role: "Principal, BrightNorth",
    quote: "Our proposals now land with the exact tone our clients expect.",
  },
];

const defaultCTA = {
  headline: "Launch your AI-driven pipeline today",
  buttonText: "Book a Strategy Session",
  note: "No credit card required • Guided onboarding",
};

const paletteItems = [
  { type: "heading", label: "Heading", html: "<h2>Campaign Title</h2>" },
  {
    type: "paragraph",
    label: "Paragraph",
    html: "<p>Share your core value proposition and measurable outcomes.</p>",
  },
  {
    type: "cta",
    label: "CTA Button",
    html: '<a href="#" style="display:inline-block;padding:12px 24px;border-radius:8px;background:#2563eb;color:#fff;text-decoration:none;">Let’s Talk</a>',
  },
  {
    type: "divider",
    label: "Divider",
    html: '<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;" />',
  },
];

const Button = ({ children, className = "", variant = "default", ...props }) => {
  const base =
    "inline-flex items-center justify-center rounded-md px-4 py-2 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2";
  const variants = {
    default: "bg-blue-600 text-white hover:bg-blue-700 focus-visible:outline-blue-600",
    secondary: "bg-white border border-gray-200 text-gray-900 hover:bg-gray-50",
    ghost: "bg-transparent text-gray-600 hover:bg-gray-50",
  };
  return (
    <button className={`${base} ${variants[variant]} ${className}`} {...props}>
      {children}
    </button>
  );
};

const Card = ({ title, children, className = "" }) => (
  <div className={`border border-gray-200 rounded-xl bg-white shadow-sm ${className}`}>
    {title && <div className="border-b border-gray-200 px-4 py-3 text-sm font-semibold text-gray-800">{title}</div>}
    <div className="p-4">{children}</div>
  </div>
);

export default function MarketingBuilder() {
  const [hero, setHero] = useState(defaultHero);
  const [services, setServices] = useState(defaultServices);
  const [testimonials, setTestimonials] = useState(defaultTestimonials);
  const [cta, setCta] = useState(defaultCTA);
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [emailBlocks, setEmailBlocks] = useState([
    { id: "intro", label: "Intro", html: "<p>Hey there — excited to collaborate!</p>" },
  ]);
  const [dragging, setDragging] = useState(null);
  const [toneTokens, setToneTokens] = useState([]);
  const [toneInput, setToneInput] = useState("");

  const marketingTemplate = useMemo(
    () => ({
      hero,
      services,
      testimonials,
      cta,
      updatedAt: new Date().toISOString(),
    }),
    [hero, services, testimonials, cta]
  );

  const handleAddService = () => {
    setServices((prev) => [...prev, { title: "New Service", description: "Describe the outcome your client gets." }]);
  };

  const handleAddTestimonial = () => {
    setTestimonials((prev) => [
      ...prev,
      { name: "Customer Name", role: "Role, Company", quote: "Share the success metric and quick story." },
    ]);
  };

  const handleSaveTemplate = async () => {
    setSaving(true);
    setMessage("");
    const payload = {
      key: `template_${Date.now()}`,
      template: marketingTemplate,
    };
    try {
      const { error } = await supabase.from("marketing_templates").upsert(payload, { onConflict: "key" });
      if (error) throw error;
      setMessage("Template saved to Supabase.");
    } catch (err) {
      console.warn("Supabase save failed, falling back to download", err);
      const blob = new Blob([JSON.stringify(marketingTemplate, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `marketing-template-${Date.now()}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      setMessage("Supabase not available; template downloaded locally.");
    } finally {
      setSaving(false);
    }
  };

  const handleDragStart = (item) => setDragging(item);
  const handleDrop = () => {
    if (!dragging) return;
    setEmailBlocks((prev) => [...prev, { ...dragging, id: `${dragging.type}-${Date.now()}` }]);
    setDragging(null);
  };

  const handleRemoveBlock = (id) => {
    setEmailBlocks((prev) => prev.filter((block) => block.id !== id));
  };

  const handleSaveEmailTemplate = async () => {
    const html = emailBlocks.map((block) => block.html).join("\n");
    try {
      await postJSON("/branding/email_templates", {
        user_id: "demo",
        name: `Campaign ${new Date().toLocaleString()}`,
        html,
        metadata: { blocks: emailBlocks.map(({ type, label }) => ({ type, label })) },
      });
      setMessage("Email template stored in workspace.");
    } catch (err) {
      console.error(err);
      setMessage(err instanceof Error ? err.message : "Failed to store email template");
    }
  };

  const handleTrainTone = async () => {
    if (!toneInput.trim()) return;
    try {
      const response = await postJSON("/branding/train_tone", { text: toneInput });
      setToneTokens(response.tokens || []);
      setMessage("Tone profile generated.");
    } catch (err) {
      console.error(err);
      setMessage(err instanceof Error ? err.message : "Failed to train tone");
    }
  };

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-semibold text-gray-900">Marketing Builder</h1>
          <p className="text-sm text-gray-600">
            Compose branded landing experiences, tone guides, and outbound campaigns for FreeAgent.
          </p>
        </div>
        <Button onClick={handleSaveTemplate} disabled={saving}>
          {saving ? "Saving..." : "Save Template"}
        </Button>
      </header>

      {message && (
        <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-2 text-sm text-blue-700">{message}</div>
      )}

      <section className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card title="Hero Section">
          <div className="flex flex-col gap-3">
            <label className="text-xs font-medium uppercase text-gray-500">Title</label>
            <input
              value={hero.title}
              onChange={(event) => setHero((prev) => ({ ...prev, title: event.target.value }))}
              className="rounded-md border border-gray-200 px-3 py-2 text-sm"
            />
            <label className="text-xs font-medium uppercase text-gray-500">Subtitle</label>
            <textarea
              value={hero.subtitle}
              onChange={(event) => setHero((prev) => ({ ...prev, subtitle: event.target.value }))}
              className="min-h-[80px] rounded-md border border-gray-200 px-3 py-2 text-sm"
            />
            <label className="text-xs font-medium uppercase text-gray-500">CTA Text</label>
            <input
              value={hero.ctaText}
              onChange={(event) => setHero((prev) => ({ ...prev, ctaText: event.target.value }))}
              className="rounded-md border border-gray-200 px-3 py-2 text-sm"
            />
            <label className="text-xs font-medium uppercase text-gray-500">Illustration URL</label>
            <input
              value={hero.illustration}
              onChange={(event) => setHero((prev) => ({ ...prev, illustration: event.target.value }))}
              className="rounded-md border border-gray-200 px-3 py-2 text-sm"
            />
          </div>
        </Card>

        <Card title="CTA Section">
          <div className="flex flex-col gap-3">
            <label className="text-xs font-medium uppercase text-gray-500">Headline</label>
            <input
              value={cta.headline}
              onChange={(event) => setCta((prev) => ({ ...prev, headline: event.target.value }))}
              className="rounded-md border border-gray-200 px-3 py-2 text-sm"
            />
            <label className="text-xs font-medium uppercase text-gray-500">Button Text</label>
            <input
              value={cta.buttonText}
              onChange={(event) => setCta((prev) => ({ ...prev, buttonText: event.target.value }))}
              className="rounded-md border border-gray-200 px-3 py-2 text-sm"
            />
            <label className="text-xs font-medium uppercase text-gray-500">Support Note</label>
            <textarea
              value={cta.note}
              onChange={(event) => setCta((prev) => ({ ...prev, note: event.target.value }))}
              className="min-h-[60px] rounded-md border border-gray-200 px-3 py-2 text-sm"
            />
          </div>
        </Card>
      </section>

      <section className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Card
          title="Services"
          className="md:col-span-1"
        >
          <div className="flex flex-col gap-4">
            {services.map((service, index) => (
              <div key={index} className="rounded-lg border border-gray-200 p-3">
                <input
                  value={service.title}
                  onChange={(event) =>
                    setServices((prev) =>
                      prev.map((item, i) => (i === index ? { ...item, title: event.target.value } : item))
                    )
                  }
                  className="mb-2 w-full rounded-md border border-gray-200 px-3 py-2 text-sm font-semibold"
                />
                <textarea
                  value={service.description}
                  onChange={(event) =>
                    setServices((prev) =>
                      prev.map((item, i) => (i === index ? { ...item, description: event.target.value } : item))
                    )
                  }
                  className="min-h-[60px] w-full rounded-md border border-gray-200 px-3 py-2 text-sm"
                />
              </div>
            ))}
            <Button variant="secondary" onClick={handleAddService}>
              Add Service
            </Button>
          </div>
        </Card>

        <Card title="Testimonials">
          <div className="flex flex-col gap-4">
            {testimonials.map((testimonial, index) => (
              <div key={index} className="rounded-lg border border-gray-200 p-3">
                <input
                  value={testimonial.name}
                  onChange={(event) =>
                    setTestimonials((prev) =>
                      prev.map((item, i) => (i === index ? { ...item, name: event.target.value } : item))
                    )
                  }
                  className="mb-2 w-full rounded-md border border-gray-200 px-3 py-2 text-sm font-semibold"
                />
                <input
                  value={testimonial.role}
                  onChange={(event) =>
                    setTestimonials((prev) =>
                      prev.map((item, i) => (i === index ? { ...item, role: event.target.value } : item))
                    )
                  }
                  className="mb-2 w-full rounded-md border border-gray-200 px-3 py-2 text-sm"
                />
                <textarea
                  value={testimonial.quote}
                  onChange={(event) =>
                    setTestimonials((prev) =>
                      prev.map((item, i) => (i === index ? { ...item, quote: event.target.value } : item))
                    )
                  }
                  className="min-h-[60px] w-full rounded-md border border-gray-200 px-3 py-2 text-sm"
                />
              </div>
            ))}
            <Button variant="secondary" onClick={handleAddTestimonial}>
              Add Testimonial
            </Button>
          </div>
        </Card>
      </section>

      <Card title="Preview">
        <div className="space-y-12 rounded-xl bg-gray-50 p-8">
          <section className="grid gap-8 md:grid-cols-2">
            <div className="space-y-4">
              <h2 className="text-4xl font-bold text-gray-900">{hero.title}</h2>
              <p className="text-lg text-gray-600">{hero.subtitle}</p>
              <Button>{hero.ctaText}</Button>
            </div>
            <div>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={hero.illustration} alt="Hero" className="w-full rounded-xl border border-gray-200" />
            </div>
          </section>

          <section>
            <h3 className="text-2xl font-semibold text-gray-900">Services</h3>
            <div className="mt-4 grid gap-4 md:grid-cols-3">
              {services.map((service, index) => (
                <div key={index} className="rounded-lg border border-gray-200 bg-white p-4">
                  <h4 className="text-lg font-semibold text-gray-900">{service.title}</h4>
                  <p className="mt-2 text-sm text-gray-600">{service.description}</p>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h3 className="text-2xl font-semibold text-gray-900">What clients say</h3>
            <div className="mt-4 space-y-4">
              {testimonials.map((testimonial, index) => (
                <blockquote key={index} className="rounded-lg border border-gray-200 bg-white p-4">
                  <p className="text-sm text-gray-700">“{testimonial.quote}”</p>
                  <span className="mt-2 block text-xs font-medium uppercase text-gray-500">
                    {testimonial.name} — {testimonial.role}
                  </span>
                </blockquote>
              ))}
            </div>
          </section>

          <section className="rounded-lg border border-blue-100 bg-blue-50 p-6 text-center">
            <h3 className="text-2xl font-semibold text-gray-900">{cta.headline}</h3>
            <p className="mt-2 text-sm text-gray-700">{cta.note}</p>
            <div className="mt-4 flex justify-center">
              <Button>{cta.buttonText}</Button>
            </div>
          </section>
        </div>
      </Card>

      <section className="grid grid-cols-1 gap-6 md:grid-cols-[240px_1fr]">
        <Card title="Email Blocks" className="md:row-span-2">
          <div className="flex flex-col gap-3">
            {paletteItems.map((item) => (
              <div
                key={item.type}
                draggable
                onDragStart={() => handleDragStart(item)}
                className="cursor-grab rounded-md border border-dashed border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 hover:border-blue-400"
              >
                {item.label}
              </div>
            ))}
          </div>
        </Card>

        <Card title="Email Designer">
          <div
            onDragOver={(event) => event.preventDefault()}
            onDrop={handleDrop}
            className="min-h-[200px] rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4"
          >
            {emailBlocks.length === 0 && (
              <p className="text-sm text-gray-500">Drag blocks here to build your campaign email.</p>
            )}
            <div className="space-y-3">
              {emailBlocks.map((block) => (
                <div key={block.id} className="relative rounded-md border border-gray-200 bg-white p-3 text-sm">
                  <div
                    className="absolute right-2 top-2 cursor-pointer text-xs text-red-500"
                    onClick={() => handleRemoveBlock(block.id)}
                  >
                    Remove
                  </div>
                  <div dangerouslySetInnerHTML={{ __html: block.html }} />
                </div>
              ))}
            </div>
          </div>
          <div className="mt-4 flex justify-end">
            <Button onClick={handleSaveEmailTemplate}>Save Campaign Template</Button>
          </div>
        </Card>
      </section>

      <Card title="Tone Trainer">
        <div className="flex flex-col gap-3">
          <textarea
            value={toneInput}
            onChange={(event) => setToneInput(event.target.value)}
            placeholder="Paste website copy or brand messaging..."
            className="min-h-[100px] rounded-md border border-gray-200 px-3 py-2 text-sm"
          />
          <div className="flex items-center justify-between">
            <div className="flex gap-2">
              {toneTokens.map((token) => (
                <span key={token} className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-600">
                  {token}
                </span>
              ))}
            </div>
            <Button variant="secondary" onClick={handleTrainTone}>
              Generate Tone Profile
            </Button>
          </div>
        </div>
      </Card>
    </main>
  );
}
