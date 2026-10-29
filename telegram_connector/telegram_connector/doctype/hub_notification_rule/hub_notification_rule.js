const SKIP_TYPES = ["Section Break", "Column Break", "Tab Break", "HTML", "Button", "Table", "Table MultiSelect", "Image", "Fold", "Heading"];

function set_title(frm) {
	if (!frm.is_new() || !frm.doc.document_type) return;
	frm.set_value("title", `${frm.doc.document_type} - ${frm.doc.event || "Submit"} - ${frm.doc.channel || "Telegram"}`);
}

const VALUE_CHANGE_MESSAGE = "{{ doc.doctype }} {{ doc.name }}: {{ field_label }} changed from {{ old_value }} to {{ new_value }} by {{ changed_by }}";
const DATE_TYPES = ["Date", "Datetime"];

// Fill the field pickers (value changed, reference date, conditions, recipients) from the document type
function setup_field_pickers(frm) {
	const dt = frm.doc.document_type;
	if (!dt) return;
	frappe.call({ method: "telegram_connector.api.get_fields", args: { doctype: dt } }).then(r => {
		const all = r.message || [];
		const opts = list => list.map(f => ({ value: f.value, label: f.label }));
		frm.set_df_property("value_changed", "options", opts(all));
		frm.set_df_property("date_changed", "options", opts(all.filter(f => DATE_TYPES.includes(f.fieldtype))));
		frm.fields_dict.conditions.grid.update_docfield_property("fieldname", "options", opts(all));
		frm.fields_dict.recipients.grid.update_docfield_property(
			"document_field", "options",
			opts(all.filter(f => ["Data", "Link", "Dynamic Link", "Phone"].includes(f.fieldtype))));
	});
}

function load_preset(frm, replace_message) {
	if (!frm.doc.document_type) return;
	frappe.call({
		method: "telegram_connector.api.get_preset",
		args: { doctype: frm.doc.document_type },
	}).then(r => {
		const p = r.message || {};
		frm.set_value({
			party_field: p.party_field || "",
			party_doctype: p.party_doctype || "",
			mobile_field: p.mobile_field || "",
			party_mobile_field: p.party_mobile_field || "",
			prefer_party_mobile: p.prefer_party_mobile ? 1 : 0,
			attach_print: p.attach_print ? 1 : 0,
			condition: p.condition || "",
		});
		const msg = frm.doc.event === "Value Change" ? VALUE_CHANGE_MESSAGE : p.message;
		if (replace_message || !frm.doc.message) frm.set_value("message", msg || "");
	});
}

function insert_field(frm) {
	const dt = frm.doc.document_type;
	if (!dt) return frappe.msgprint(__("Select a Document Type first"));
	frappe.model.with_doctype(dt, () => {
		const meta = frappe.get_meta(dt);
		const opts = [
			{ label: __("Document Name (name)"), value: "{{ doc.name }}" },
			{ label: __("Changed By (user full name)"), value: "{{ changed_by }}" },
			{ label: __("Value Change: field label"), value: "{{ field_label }}" },
			{ label: __("Value Change: old value"), value: "{{ old_value }}" },
			{ label: __("Value Change: new value"), value: "{{ new_value }}" },
		];
		meta.fields
			.filter(f => !SKIP_TYPES.includes(f.fieldtype))
			.forEach(f => opts.push({
				label: `${f.label || f.fieldname} (${f.fieldname})`,
				value: `{{ doc.${f.fieldname} }}`,
			}));
		if (meta.fields.some(f => f.fieldname === "items" && f.fieldtype === "Table")) {
			opts.push({
				label: __("Items list (loop)"),
				value: "{% for i in doc.items %}• {{ i.item_name }} × {{ i.qty }} = {{ i.amount }}\n{% endfor %}",
			});
		}
		const d = new frappe.ui.Dialog({
			title: __("Insert Field"),
			fields: [{ fieldname: "field", fieldtype: "Autocomplete", label: __("Field"), options: opts, reqd: 1 }],
			primary_action_label: __("Insert"),
			primary_action(v) {
				const cur = frm.doc.message || "";
				const sep = cur && !cur.endsWith("\n") ? "\n" : "";
				frm.set_value("message", cur + sep + v.field);
				d.hide();
			},
		});
		d.show();
	});
}

function preview(frm) {
	const dt = frm.doc.document_type;
	if (!dt) return frappe.msgprint(__("Select a Document Type first"));
	const d = new frappe.ui.Dialog({
		title: __("Preview Message"),
		fields: [{ fieldname: "docname", fieldtype: "Link", label: dt, options: dt, reqd: 1 }],
		primary_action_label: __("Preview"),
		primary_action(v) {
			frappe.call({
				method: "telegram_connector.api.preview_message",
				args: { doctype: dt, name: v.docname, message: frm.doc.message || "" },
			}).then(r => {
				d.hide();
				frappe.msgprint({
					title: __("Preview"),
					message: `<pre style="white-space: pre-wrap; font-family: inherit;">${frappe.utils.escape_html(r.message || "")}</pre>`,
				});
			});
		},
	});
	d.show();
}

frappe.ui.form.on("Hub Notification Rule", {
	refresh(frm) {
		setup_field_pickers(frm);
		frm.add_custom_button(__("Insert Field"), () => insert_field(frm), __("Template"));
		frm.add_custom_button(__("Preview"), () => preview(frm), __("Template"));
		frm.add_custom_button(__("Load Default Template"), () =>
			frappe.confirm(__("Replace the recipient fields and message with the default template?"), () =>
				load_preset(frm, true)), __("Template"));

		// New rule: pick the channel from what is enabled in Notification Hub
		if (frm.is_new() && !frm.__channel_set) {
			frm.__channel_set = true;
			frappe.call({ method: "telegram_connector.api.get_enabled_channels" }).then(r => {
				const ch = r.message || [];
				if (ch.length === 2) frm.set_value("channel", "Both");
				else if (ch.length === 1) frm.set_value("channel", ch[0]);
			});
		}
	},
	document_type(frm) {
		setup_field_pickers(frm);
		if (!frm.is_new()) return;
		load_preset(frm, true);
		set_title(frm);
	},
	event(frm) {
		set_title(frm);
		// a status-change rule needs a different message than a document rule
		if (frm.is_new() && frm.doc.event === "Value Change") frm.set_value("message", VALUE_CHANGE_MESSAGE);
	},
	channel: set_title,
});
