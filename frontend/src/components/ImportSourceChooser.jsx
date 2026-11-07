import React from "react";
import { Description, Dialog, DialogBackdrop, DialogPanel, DialogTitle } from "@headlessui/react";
import { FaApple, FaAndroid, FaGoogle, FaWhatsapp, FaMicrosoft, FaFileCsv, FaFileExcel, FaTable, FaAddressBook, FaArrowRight, FaTimes } from "react-icons/fa";
import { SOURCES } from "./contactImportSources";
import "./ImportSourceChooser.css";

const ICONS = { apple: FaApple, android: FaAndroid, google: FaGoogle, whatsapp: FaWhatsapp, outlook: FaMicrosoft, sheets: FaTable, excel: FaFileExcel, other: FaFileCsv };

export default function ImportSourceChooser({ open, onClose, onSelect }) {
  return (
    <Dialog open={open} onClose={onClose} className="import-chooser">
      <DialogBackdrop className="import-chooser-backdrop" />
      <div className="import-chooser-position">
        <DialogPanel className="import-chooser-panel">
          <div className="import-chooser-header">
            <div>
              <p className="import-chooser-eyebrow">IMPORT CONTACTS</p>
              <DialogTitle>Where are your contacts?</DialogTitle>
              <Description>Choose a service to see the right import steps. You’ll review your contacts before saving them.</Description>
            </div>
            <button type="button" className="import-chooser-close" onClick={onClose} aria-label="Close import source chooser" data-autofocus><FaTimes aria-hidden="true" /></button>
          </div>
          { ["Contacts & spreadsheets", "CRMs"].map(group => (
            <section className="import-chooser-group" key={group} aria-label={group}>
              <h3>{group}</h3>
              <div className="import-chooser-grid">
                {SOURCES.filter(source => source.group === group).map(source => {
                  const Icon = ICONS[source.key] || FaAddressBook;
                  return (
                    <button type="button" className="import-chooser-option" key={source.key} onClick={() => onSelect(source.key)} aria-label={source.label}>
                      <span className={`import-chooser-icon import-chooser-icon-${source.key}`}><Icon aria-hidden="true" /></span>
                      <span className="import-chooser-copy"><strong>{source.label}</strong><small>{source.detail}</small></span>
                      <FaArrowRight className="import-chooser-arrow" aria-hidden="true" />
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
          <p className="import-chooser-note">Importing never sends a message or records marketing consent.</p>
        </DialogPanel>
      </div>
    </Dialog>
  );
}
