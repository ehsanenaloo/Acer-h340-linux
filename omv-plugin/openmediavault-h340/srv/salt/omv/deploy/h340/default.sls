{% set config = salt['omv_conf.get']('conf.service.h340') %}

{% if config.enable | to_bool and config.sharedfolderref %}

configure_h340_usb_backup:
  file.managed:
    - name: /etc/h340-usb-backup.json
    - source:
      - salt://{{ tpldir }}/files/usb-backup.json.j2
    - context:
        config: {{ config | json }}
    - template: jinja
    - user: root
    - group: root
    - mode: '0644'

start_h340_usb_backup_service:
  service.running:
    - name: h340-usb-backup
    - enable: True
    - watch:
      - file: configure_h340_usb_backup

{% else %}

stop_h340_usb_backup_service:
  service.dead:
    - name: h340-usb-backup
    - enable: False

{% endif %}

{% if config.ledenable | to_bool %}

configure_h340_leds:
  file.managed:
    - name: /etc/h340-leds.json
    - source:
      - salt://{{ tpldir }}/files/leds.json.j2
    - context:
        config: {{ config | json }}
    - template: jinja
    - user: root
    - group: root
    - mode: '0644'

start_h340_leds_service:
  service.running:
    - name: h340-leds
    - enable: True
    - watch:
      - file: configure_h340_leds

{# Only a service installed by the h340-leds package is stopped here. #}
{% elif salt['file.file_exists']('/usr/lib/h340-leds/h340_leds.py') %}

stop_h340_leds_service:
  service.dead:
    - name: h340-leds
    - enable: False

{% endif %}
