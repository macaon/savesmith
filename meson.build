project('savesmith',
  version: '0.1.0',
  meson_version: '>= 1.0.0',
  license: 'GPL-3.0-or-later',
)

python = import('python').find_installation('python3', required: true)
gnome = import('gnome')

app_id = 'io.github.savesmith'

install_data(
  'bin/savesmith',
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)

subdir('savesmith')
subdir('data')

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
