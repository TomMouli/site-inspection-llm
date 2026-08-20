const notes = document.querySelector('#notes');
const count = document.querySelector('#char-count');
const example = `Visited the Riverside Community Center for Maya Patel.\nAddress: 42 Harbor Street, Portland, OR 97205.\nThe rooftop has 18 aging solar panels and one inverter showing a red fault light.\nClient is considering a replacement and battery storage. Estimated budget is $24,000.\nPlease schedule a follow-up before October 15, 2026.`;

function updateCount() {
  if (notes && count) count.textContent = `${notes.value.length} / 5000`;
}
if (notes) {
  notes.addEventListener('input', updateCount);
  updateCount();
}
document.querySelector('#example-btn')?.addEventListener('click', () => {
  notes.value = example;
  updateCount();
  notes.focus();
});

document.querySelectorAll('.remove-chip').forEach((button) => {
  button.addEventListener('click', () => button.closest('.chip').remove());
});

document.querySelector('#reset-btn')?.addEventListener('click', () => {
  const data = window.siteData;
  document.querySelectorAll('.editable').forEach((field) => {
    const key = field.dataset.field;
    if (field.tagName === 'SELECT') field.value = data[key];
    else if (field.dataset.field !== 'equipment') field.value = data[key] || '';
  });
  document.querySelector('#save-status').textContent = 'Edits reset.';
});

document.querySelector('#save-btn')?.addEventListener('click', async () => {
  const data = {};
  document.querySelectorAll('[data-field]').forEach((field) => {
    if (field.dataset.field === 'equipment') {
      data.equipment = [...field.querySelectorAll('.chip')].map((chip) => chip.textContent.replace('×', '').trim());
    } else data[field.dataset.field] = field.value;
  });
  const status = document.querySelector('#save-status');
  status.textContent = 'Saving...';
  try {
    const response = await fetch('/api/sites/save/', {
      method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value}, body: JSON.stringify(data)
    });
    const result = await response.json();
    status.textContent = response.ok ? 'Saved and validated.' : result.error;
  } catch (error) {
    status.textContent = 'Could not reach the server.';
  }
});
